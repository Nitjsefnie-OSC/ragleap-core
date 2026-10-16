package com.ragleap.graph;

import static com.ragleap.graph.MigrationFakes.canon;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.lang.reflect.Proxy;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Compares PostgresAuditSink with the real Python AuditLogger (stubbed psycopg2): every connect, autocommit, execute
 * with its parameters, close, and the kinds of warnings, for 27 scripted scenarios.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class AuditSinkParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static List<Object> ev(Object... items) {
        return new ArrayList<>(Arrays.asList(items));
    }

    private static String text(JsonNode n, String key) {
        return n.hasNonNull(key) ? n.get(key).asText() : null;
    }

    private static Object decode(JsonNode n) {
        if (n.isNull()) {
            return null;
        }
        if (n.isObject()) {
            if (n.size() == 1 && n.has("__set__")) {
                HashSet<Object> set = new HashSet<>();
                n.get("__set__").forEach(e -> set.add(decode(e)));
                return set;
            }
            if (n.size() == 1 && n.has("__float__")) {
                return switch (n.get("__float__").asText()) {
                    case "nan" -> Double.NaN;
                    case "inf" -> Double.POSITIVE_INFINITY;
                    case "-inf" -> Double.NEGATIVE_INFINITY;
                    default -> throw new IllegalStateException("unknown float marker");
                };
            }
            Map<String, Object> map = new LinkedHashMap<>();
            n.fields().forEachRemaining(e -> map.put(e.getKey(), decode(e.getValue())));
            return map;
        }
        if (n.isArray()) {
            List<Object> list = new ArrayList<>();
            n.forEach(e -> list.add(decode(e)));
            return list;
        }
        if (n.isBoolean()) {
            return n.booleanValue();
        }
        if (n.isTextual()) {
            return n.textValue();
        }
        if (n.isIntegralNumber()) {
            return n.canConvertToInt() ? (Object) n.intValue() : (Object) n.longValue();
        }
        return n.doubleValue();
    }

    private static String kind(String msg) {
        if (msg.startsWith("Audit log connection failed")) {
            return "connect_failed";
        }
        if (msg.startsWith("Audit log schema setup failed")) {
            return "schema_failed";
        }
        if (msg.startsWith("Audit log write failed")) {
            return "write_failed";
        }
        if (msg.startsWith("PostgreSQL JDBC driver not found")) {
            return "no_driver";
        }
        return "other:" + msg;
    }

    static final class Harness {
        final JsonNode sc;
        final List<Object> events = new ArrayList<>();
        int connects;
        int executes;
        String currentOp = "";

        Harness(JsonNode sc) {
            this.sc = sc;
        }

        private void recordExecute(String sql, Object[] params) throws SQLException {
            int i = executes++;
            events.add(ev("execute", sql.replaceAll("\\s+", ""), new ArrayList<>(Arrays.asList(params))));
            for (JsonNode f : sc.get("execute_failures")) {
                if (f.asInt() == i) {
                    throw new SQLException("scripted execute failure");
                }
            }
        }

        private Object statement() {
            return Proxy.newProxyInstance(Harness.class.getClassLoader(), new Class<?>[] {java.sql.Statement.class},
                    (p, m, a) -> switch (m.getName()) {
                        case "execute" -> {
                            recordExecute((String) a[0], new Object[0]);
                            yield false;
                        }
                        case "close" -> null;
                        case "hashCode" -> System.identityHashCode(p);
                        case "equals" -> p == a[0];
                        case "toString" -> "FakeStatement";
                        default -> throw new UnsupportedOperationException(m.getName());
                    });
        }

        private Object prepared(String sql) {
            Object[] params = new Object[6];
            return Proxy.newProxyInstance(Harness.class.getClassLoader(),
                    new Class<?>[] {java.sql.PreparedStatement.class}, (p, m, a) -> switch (m.getName()) {
                        case "setString" -> {
                            params[(Integer) a[0] - 1] = a[1];
                            yield null;
                        }
                        case "setNull" -> {
                            params[(Integer) a[0] - 1] = null;
                            yield null;
                        }
                        case "setInt" -> {
                            params[(Integer) a[0] - 1] = a[1];
                            yield null;
                        }
                        case "setObject" -> {
                            params[(Integer) a[0] - 1] = a[1];
                            yield null;
                        }
                        case "execute" -> {
                            recordExecute(sql, params);
                            yield false;
                        }
                        case "close" -> null;
                        case "hashCode" -> System.identityHashCode(p);
                        case "equals" -> p == a[0];
                        case "toString" -> "FakePreparedStatement";
                        default -> throw new UnsupportedOperationException(m.getName());
                    });
        }

        Connection open(String url) throws SQLException, PostgresAuditSink.DriverMissingException {
            if (sc.get("driver_missing").asBoolean()) {
                throw new PostgresAuditSink.DriverMissingException();
            }
            int i = connects++;
            events.add(ev("connect", url));
            JsonNode results = sc.get("connect_results");
            if (i < results.size() && !results.get(i).asBoolean()) {
                throw new SQLException("scripted connect failure");
            }
            return (Connection) Proxy.newProxyInstance(Harness.class.getClassLoader(), new Class<?>[] {Connection.class},
                    (p, m, a) -> switch (m.getName()) {
                        case "setAutoCommit" -> {
                            events.add(ev("autocommit", a[0]));
                            yield null;
                        }
                        case "createStatement" -> statement();
                        case "prepareStatement" -> prepared((String) a[0]);
                        case "close" -> {
                            // Python never closes a dropped connection; Java does. Only closes made by close() count.
                            if (currentOp.equals("close")) {
                                events.add(ev("close"));
                            }
                            if (sc.get("close_fails").asBoolean()) {
                                throw new SQLException("scripted close failure");
                            }
                            yield null;
                        }
                        case "isClosed" -> false;
                        case "hashCode" -> System.identityHashCode(p);
                        case "equals" -> p == a[0];
                        case "toString" -> "FakeConnection";
                        default -> throw new UnsupportedOperationException(m.getName());
                    });
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void auditSinkMatchesPython() throws IOException {
        JsonNode cases = MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"), "audit_cases.json")
                .toFile()).get("cases");
        assertTrue(cases.size() >= 27, "fixture count: " + cases.size());
        List<String> bad = new ArrayList<>();
        Logger logger = Logger.getLogger("ragleap_graph.audit");
        boolean useParent = logger.getUseParentHandlers();
        for (JsonNode sc : cases) {
            String name = sc.get("name").asText();
            Harness h = new Harness(sc);
            List<String> kinds = new ArrayList<>();
            Handler handler = new Handler() {
                @Override
                public void publish(LogRecord r) {
                    if (r.getLevel().intValue() >= Level.WARNING.intValue()) {
                        kinds.add(kind(r.getMessage()));
                    }
                }

                @Override
                public void flush() {
                }

                @Override
                public void close() {
                }
            };
            logger.addHandler(handler);
            logger.setUseParentHandlers(false);
            try {
                JsonNode cfg = sc.get("config");
                String url = cfg.isNull() || cfg.get("database_url").isNull() ? null : cfg.get("database_url").asText();
                PostgresAuditSink sink = new PostgresAuditSink(url, h::open);
                for (JsonNode op : sc.get("ops")) {
                    h.currentOp = op.get(0).asText();
                    if (h.currentOp.equals("log")) {
                        JsonNode a = op.get(1);
                        Integer entityCount = a.hasNonNull("entity_count") ? Integer.valueOf(a.get("entity_count").asInt())
                                : null;
                        Map<String, Object> detail = a.hasNonNull("detail") ? (Map<String, Object>) decode(a.get("detail"))
                                : null;
                        sink.log(text(a, "user_id"), text(a, "namespace"), a.get("action").asText(),
                                text(a, "document_id"), entityCount, detail);
                    } else {
                        sink.close();
                    }
                }
            } finally {
                logger.removeHandler(handler);
                logger.setUseParentHandlers(useParent);
            }
            if (!canon(sc.get("events")).equals(canon(h.events))) {
                bad.add(name + ": events differ\n  python: " + canon(sc.get("events")) + "\n  java:   " + canon(h.events));
            }
            List<String> expected = new ArrayList<>();
            sc.get("warnings").forEach(w -> expected.add(w.asText()));
            if (!expected.equals(kinds)) {
                bad.add(name + ": warnings " + expected + " (python) vs " + kinds + " (java)");
            }
        }
        assertTrue(bad.isEmpty(), () -> cases.size() + " scenarios, " + bad.size() + " problems:\n"
                + String.join("\n", bad));
    }
}
