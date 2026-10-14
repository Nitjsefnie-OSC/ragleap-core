package com.ragleap.graph;

import static com.ragleap.graph.BackfillParityTest.callKeys;
import static com.ragleap.graph.BackfillParityTest.text;
import static com.ragleap.graph.MigrationFakes.DEFAULT_STATUS_ROW;
import static com.ragleap.graph.MigrationFakes.MAPPER;
import static com.ragleap.graph.MigrationFakes.canon;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.ragleap.graph.MigrationFakes.Call;
import com.ragleap.graph.MigrationFakes.SessionFake;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.LongSupplier;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares the migration runner and the registry with the real Python code, call by call. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class MigrationParityTest {
    private static final TypeReference<Map<String, Map<String, List<Map<String, Object>>>>> ROWS = new TypeReference<>() { };
    private static final TypeReference<LinkedHashMap<String, Object>> MAP = new TypeReference<>() { };

    static final class SpecMigration extends Migration {
        private final JsonNode spec;

        SpecMigration(JsonNode spec) {
            this.spec = spec;
        }

        @Override
        public String id() {
            return spec.get("id").asText();
        }

        @Override
        public String description() {
            return spec.has("description") ? spec.get("description").asText() : "fake migration";
        }

        @Override
        public Map<String, Object> up(CypherRunner session) {
            if (spec.has("raises")) {
                throw new IllegalArgumentException(spec.get("raises").asText());
            }
            if (!spec.has("result")) {
                return Map.of("updated", 1);
            }
            JsonNode r = spec.get("result");
            return r.isNull() ? null : MAPPER.convertValue(r, MAP);
        }
    }

    private static JsonNode load(String file) throws IOException {
        return MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"), file).toFile());
    }

    private static String kind(RuntimeException e) {
        if (e instanceof IllegalStateException) {
            return "RuntimeError";
        }
        if (e instanceof UnsupportedOperationException) {
            return "NotImplementedError";
        }
        return e.getClass().getSimpleName();
    }

    @Test
    void runnerBehavesLikePython() throws IOException {
        JsonNode cases = load("migrations_cases.json").get("cases");
        assertTrue(cases.size() >= 19, "fixture count: " + cases.size());
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            boolean registry = c.has("registry") && c.get("registry").asBoolean();
            List<Migration> migs = new ArrayList<>();
            if (registry) {
                migs.addAll(Migrations.all());
            } else {
                for (JsonNode s : c.get("migrations")) {
                    migs.add(new SpecMigration(s));
                }
            }
            List<String> applied = new ArrayList<>();
            if (c.has("applied_ids")) {
                c.get("applied_ids").forEach(a -> applied.add(a.asText()));
            }
            Map<String, Object> statusRow = DEFAULT_STATUS_ROW;
            if (c.has("status_row")) {
                statusRow = c.get("status_row").isNull() ? null : MAPPER.convertValue(c.get("status_row"), MAP);
            }
            Map<String, Map<String, List<Map<String, Object>>>> rows = c.has("rows")
                    ? MAPPER.convertValue(c.get("rows"), ROWS) : Map.of();
            SessionFake fake = new SessionFake(applied, rows, statusRow);
            long step = c.has("clock_step_ns") ? c.get("clock_step_ns").asLong() : 7_500_000L;
            long[] n = {0};
            LongSupplier clock = () -> n[0]++ * step;

            MigrationRunner runner;
            try {
                runner = new MigrationRunner(c.has("driver_none") && c.get("driver_none").asBoolean() ? null : fake, migs, clock);
            } catch (IllegalStateException e) {
                if (!c.has("ctor_raises") || !"RuntimeError".equals(c.get("ctor_raises").asText())
                        || !Objects.equals(c.get("ctor_message").asText(), e.getMessage())) {
                    failures.add(name + ": unexpected constructor error: " + e.getMessage());
                }
                continue;
            }
            if (c.has("ctor_raises")) {
                failures.add(name + ": python raised in the constructor, java did not");
                continue;
            }
            JsonNode opsOut = c.get("ops_out");
            for (int i = 0; i < opsOut.size(); i++) {
                JsonNode op = c.get("ops").get(i);
                JsonNode exp = opsOut.get(i);
                Object result = null;
                String raised = null;
                String message = null;
                try {
                    switch (op.get("op").asText()) {
                        case "run_pending" -> result = runner.runPending(op.has("dry_run") && op.get("dry_run").asBoolean());
                        case "status" -> result = runner.status();
                        case "down" -> result = migs.get(op.get("index").asInt()).down(null);
                        default -> throw new IllegalStateException("unknown op in fixture");
                    }
                } catch (UnsupportedOperationException | IllegalStateException e) {
                    if (e.getMessage() != null && e.getMessage().startsWith("unknown op")) {
                        throw e;
                    }
                    raised = kind(e);
                    message = e.getMessage();
                }
                String expRaise = text(exp.get("raises"));
                if (!Objects.equals(expRaise, raised)) {
                    failures.add(name + " op " + i + ": raises " + expRaise + " (python) vs " + raised + " (java)");
                } else if (expRaise != null) {
                    if (!Objects.equals(text(exp.get("message")), message)) {
                        failures.add(name + " op " + i + ": message\n  python: " + text(exp.get("message"))
                                + "\n  java:   " + message);
                    }
                } else if (!canon(exp.get("result")).equals(canon(result))) {
                    failures.add(name + " op " + i + ": result\n  python: " + canon(exp.get("result"))
                            + "\n  java:   " + canon(result));
                }
                if (expRaise != null) {
                    break;
                }
            }
            List<String> expected = callKeys(c.get("calls"));
            List<String> actual = fake.calls.stream().map(Call::key).toList();
            if (!expected.equals(actual)) {
                failures.add(name + ": statements differ\n  python: " + expected + "\n  java:   " + actual);
            }
            List<String> expIds = new ArrayList<>();
            c.get("sorted_ids").forEach(s -> expIds.add(s.asText()));
            if (!expIds.equals(runner.migrations().stream().map(Migration::id).toList())) {
                failures.add(name + ": sort order differs: " + expIds + " vs "
                        + runner.migrations().stream().map(Migration::id).toList());
            }
        }
        assertTrue(failures.isEmpty(), () -> String.join("\n", failures));
    }

    @Test
    void registryMatchesPython() throws IOException {
        JsonNode registry = load("migrations_cases.json").get("registry");
        List<Migration> all = Migrations.all();
        assertEquals(registry.size(), all.size());
        for (int i = 0; i < all.size(); i++) {
            assertEquals(registry.get(i).get("id").asText(), all.get(i).id());
            assertEquals(registry.get(i).get("description").asText(), all.get(i).description());
        }
    }
}
