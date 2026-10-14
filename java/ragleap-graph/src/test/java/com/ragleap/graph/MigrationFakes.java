package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Test helpers: a fake session that behaves like the Python fakes and records every statement. */
final class MigrationFakes {
    static final ObjectMapper MAPPER = new ObjectMapper();
    static final Map<String, Object> DEFAULT_STATUS_ROW = row("applied_at", "2026-01-01T00:00:00Z", "elapsed_ms", 42);

    private MigrationFakes() {
    }

    static Map<String, Object> row(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    static String strip(String s) {
        return s.replaceAll("\\s+", "");
    }

    /** Canonical text of a JSON-like value: sorted keys, integers and floats kept apart. */
    static String canon(Object o) {
        JsonNode n = o instanceof JsonNode j ? j : MAPPER.valueToTree(o);
        StringBuilder sb = new StringBuilder();
        canon(n, sb);
        return sb.toString();
    }

    private static void canon(JsonNode n, StringBuilder sb) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            sb.append("null");
        } else if (n.isObject()) {
            List<String> names = new ArrayList<>();
            n.fieldNames().forEachRemaining(names::add);
            Collections.sort(names);
            sb.append('{');
            for (String k : names) {
                sb.append('"').append(k.replace("\\", "\\\\").replace("\"", "\\\"")).append("\":");
                canon(n.get(k), sb);
                sb.append(',');
            }
            sb.append('}');
        } else if (n.isArray()) {
            sb.append('[');
            for (JsonNode e : n) {
                canon(e, sb);
                sb.append(',');
            }
            sb.append(']');
        } else if (n.isTextual()) {
            sb.append('"').append(n.asText().replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
        } else if (n.isBoolean()) {
            sb.append(n.asBoolean());
        } else if (n.isIntegralNumber()) {
            sb.append('i').append(n.bigIntegerValue());
        } else {
            sb.append('f').append(n.doubleValue());
        }
    }

    record Call(String cypher, String params) {
        String key() {
            return cypher + "|" + params;
        }
    }

    /** Mirrors the Python FakeSession/Session used when the fixtures were recorded. */
    static final class SessionFake implements CypherRunner {
        final List<Call> calls = new ArrayList<>();
        final List<Map<String, Object>> created = new ArrayList<>();
        final Set<String> applied = new LinkedHashSet<>();
        private final Map<String, Map<String, List<Map<String, Object>>>> rows;
        private final Map<String, Object> statusRow;

        SessionFake() {
            this(List.of(), Map.of(), DEFAULT_STATUS_ROW);
        }

        SessionFake(Collection<String> applied, Map<String, Map<String, List<Map<String, Object>>>> rows,
                Map<String, Object> statusRow) {
            this.applied.addAll(applied);
            this.rows = rows;
            this.statusRow = statusRow;
        }

        private static List<Map<String, Object>> copy(List<Map<String, Object>> src) {
            List<Map<String, Object>> out = new ArrayList<>();
            for (Map<String, Object> m : src) {
                out.add(new LinkedHashMap<>(m));
            }
            return out;
        }

        private static String labelOf(String q) {
            if (q.contains("CO_OCCURS_WITH")) {
                return "co";
            }
            for (String label : List.of("RelationWeight", "PairWeight", "Document", "Entity")) {
                if (q.contains("(n:" + label + ")")) {
                    return label;
                }
            }
            return null;
        }

        @Override
        public List<Map<String, Object>> run(String cypher, Map<String, Object> params) {
            calls.add(new Call(strip(cypher), canon(params)));
            if (cypher.contains("RETURN count(m) > 0 AS applied")) {
                return List.of(row("applied", applied.contains((String) params.get("id"))));
            }
            if (cypher.contains("CREATE (m:_Migration")) {
                applied.add((String) params.get("id"));
                created.add(new LinkedHashMap<>(params));
                return List.of();
            }
            if (cypher.contains("RETURN m.applied_at AS applied_at")) {
                return statusRow == null ? List.of() : List.of(new LinkedHashMap<>(statusRow));
            }
            if (cypher.contains("UNWIND")) {
                return List.of();
            }
            String label = labelOf(cypher);
            if (cypher.contains("user_id IS NULL")) {
                return copy(rows.getOrDefault("user_id", Map.of()).getOrDefault(label, List.of()));
            }
            if (cypher.contains("composite_key IS NULL")) {
                return copy(rows.getOrDefault("composite", Map.of()).getOrDefault(label, List.of()));
            }
            throw new AssertionError("unexpected query: " + cypher);
        }
    }
}
