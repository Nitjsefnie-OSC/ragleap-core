package com.ragleap.graph;

import static com.ragleap.graph.MigrationFakes.DEFAULT_STATUS_ROW;
import static com.ragleap.graph.MigrationFakes.MAPPER;
import static com.ragleap.graph.MigrationFakes.canon;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.ragleap.graph.MigrationFakes.Call;
import com.ragleap.graph.MigrationFakes.SessionFake;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares Cypher, parameters, results and errors of the three backfills with the real Python code. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class BackfillParityTest {
    private static final TypeReference<Map<String, Map<String, List<Map<String, Object>>>>> ROWS = new TypeReference<>() { };

    static String text(JsonNode n) {
        return n == null || n.isNull() ? null : n.asText();
    }

    static List<String> callKeys(JsonNode calls) {
        List<String> out = new ArrayList<>();
        for (JsonNode c : calls) {
            out.add(c.get("cypher").asText() + "|" + canon(c.get("params")));
        }
        return out;
    }

    @Test
    void behavesLikePython() throws IOException {
        JsonNode cases = MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"), "backfill_cases.json").toFile());
        assertTrue(cases.size() >= 24, "fixture count: " + cases.size());
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            JsonNode args = c.get("args");
            SessionFake fake = c.get("no_driver").asBoolean() ? null
                    : new SessionFake(List.of(), MAPPER.convertValue(c.get("rows"), ROWS), DEFAULT_STATUS_ROW);
            String ns = text(args.get("namespace"));
            int batch = args.has("batch_size") ? args.get("batch_size").asInt() : GraphBackfills.DEFAULT_BATCH_SIZE;
            Object result = null;
            String raised = null;
            try {
                switch (c.get("method").asText()) {
                    case "backfill_user_id_defaults" -> result = GraphBackfills.userIdDefaults(fake, ns);
                    case "backfill_composite_key" -> result = GraphBackfills.compositeKey(fake, ns, batch);
                    case "backfill_co_occurs_with_composite_key" -> result = GraphBackfills.coOccursCompositeKey(fake, ns, batch);
                    default -> throw new IllegalStateException("unknown method in fixture: " + c.get("method"));
                }
            } catch (IllegalArgumentException e) {
                raised = "ValueError";
            }
            String expectedRaise = text(c.get("raises"));
            if (!Objects.equals(expectedRaise, raised)) {
                failures.add(name + ": raises " + expectedRaise + " (python) vs " + raised + " (java)");
            }
            List<String> expected = callKeys(c.get("calls"));
            List<String> actual = fake == null ? List.of() : fake.calls.stream().map(Call::key).toList();
            if (!expected.equals(actual)) {
                failures.add(name + ": statements differ\n  python: " + expected + "\n  java:   " + actual);
            }
            if (expectedRaise == null && !canon(c.get("result")).equals(canon(result))) {
                failures.add(name + ": result " + canon(c.get("result")) + " (python) vs " + canon(result) + " (java)");
            }
        }
        assertTrue(failures.isEmpty(), () -> String.join("\n", failures));
    }
}
