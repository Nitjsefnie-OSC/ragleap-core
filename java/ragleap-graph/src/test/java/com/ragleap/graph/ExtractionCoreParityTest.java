package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares the pure extraction parts with the real Python code, case by case. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class ExtractionCoreParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final LlmClient STUB = (s, q, t, d, f, temp) -> null;

    private static JsonNode cases(String section) throws IOException {
        JsonNode root = MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"),
                "extraction_core_cases.json").toFile());
        return root.get(section);
    }

    private static List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        n.forEach(e -> out.add(e.asText()));
        return out;
    }

    private static double threshold(JsonNode t) {
        return t.isTextual() ? Double.NaN : t.asDouble();
    }

    @Test
    void ratioMatchesPython() throws IOException {
        JsonNode cs = cases("ratio");
        assertTrue(cs.size() >= 400, "fixture count: " + cs.size());
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cs) {
            double expected = c.get("ratio").asDouble();
            double actual = SequenceMatch.ratio(c.get("a").asText(), c.get("b").asText());
            if (Double.compare(expected, actual) != 0) {
                failures.add("ratio(" + c.get("a").asText().length() + " chars, " + c.get("b").asText().length()
                        + " chars): python " + expected + " vs java " + actual + " | a=" + c.get("a").asText()
                        + " b=" + c.get("b").asText());
            }
        }
        assertTrue(failures.isEmpty(), () -> failures.size() + " mismatches, first: " + failures.get(0));
    }

    @Test
    void normalizeMatchesPython() throws IOException {
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cases("normalize")) {
            String actual = EntityDeduplicator.normalize(c.get("name").asText());
            if (!c.get("normalized").asText().equals(actual)) {
                failures.add("normalize(" + PyRepr.str(c.get("name").asText()) + "): python "
                        + PyRepr.str(c.get("normalized").asText()) + " vs java " + PyRepr.str(actual));
            }
        }
        assertTrue(failures.isEmpty(), () -> String.join("\n", failures));
    }

    @Test
    void resolveMatchesPython() throws IOException {
        JsonNode cs = cases("resolve");
        assertTrue(cs.size() >= 100, "fixture count: " + cs.size());
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cs) {
            double t = threshold(c.get("threshold"));
            if (c.has("error")) {
                boolean raised = false;
                String message = null;
                try {
                    new EntityDeduplicator(t);
                } catch (IllegalArgumentException e) {
                    raised = true;
                    message = e.getMessage();
                }
                boolean expectRaise = !c.get("error").isNull();
                if (expectRaise != raised || (raised && !c.get("message").asText().equals(message))) {
                    failures.add("threshold " + c.get("threshold") + ": error mismatch (" + message + ")");
                }
                continue;
            }
            Map<String, String> actual = new EntityDeduplicator(t).resolve(strings(c.get("names")));
            List<List<String>> expected = new ArrayList<>();
            c.get("mapping").forEach(p -> expected.add(List.of(p.get(0).asText(), p.get(1).asText())));
            List<List<String>> got = new ArrayList<>();
            actual.forEach((k, v) -> got.add(List.of(k, v)));
            if (!expected.equals(got)) {
                failures.add("resolve " + c.get("names") + " @" + t + "\n  python: " + expected + "\n  java:   " + got);
            }
        }
        assertTrue(failures.isEmpty(), () -> failures.size() + " mismatches:\n" + String.join("\n", failures));
    }

    @Test
    void configMatchesPython() throws IOException {
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cases("config")) {
            String name = c.get("name").asText();
            JsonNode k = c.get("kwargs");
            ExtractionConfig.Builder b = ExtractionConfig.builder();
            if (k.has("method")) {
                b.method("llm".equals(k.get("method").asText()) ? ExtractionConfig.Method.LLM
                        : ExtractionConfig.Method.REGEX);
            }
            if (k.has("dedup_enabled")) {
                b.dedupEnabled(k.get("dedup_enabled").asBoolean());
            }
            if (k.has("dedup_threshold")) {
                b.dedupThreshold(threshold(k.get("dedup_threshold")));
            }
            if (k.has("max_entities_per_chunk")) {
                b.maxEntitiesPerChunk(k.get("max_entities_per_chunk").asInt());
            }
            if (k.has("extract_relations")) {
                b.extractRelations(k.get("extract_relations").asBoolean());
            }
            if (k.has("cross_chunk_relations")) {
                b.crossChunkRelations(k.get("cross_chunk_relations").asBoolean());
            }
            if (k.has("entity_types") && !k.get("entity_types").isNull()) {
                b.entityTypes(strings(k.get("entity_types")));
            }
            if (k.has("relation_ontology") && !k.get("relation_ontology").isNull()) {
                Map<String, ExtractionConfig.Ontology> ont = new LinkedHashMap<>();
                k.get("relation_ontology").fields().forEachRemaining(e -> ont.put(e.getKey(),
                        new ExtractionConfig.Ontology(strings(e.getValue().get(0)), strings(e.getValue().get(1)))));
                b.relationOntology(ont);
            }
            if (c.get("provider").asBoolean()) {
                b.llm(STUB);
            }
            ExtractionConfig cfg = null;
            String message = null;
            try {
                cfg = b.build();
            } catch (IllegalArgumentException e) {
                message = e.getMessage();
            }
            if (c.get("ok").asBoolean()) {
                if (cfg == null) {
                    failures.add(name + ": python accepted, java threw: " + message);
                    continue;
                }
                JsonNode f = c.get("fields");
                List<String> pyTypes = f.get("entity_types").isNull() ? List.of() : strings(f.get("entity_types"));
                boolean same = f.get("method").asText().equals(cfg.method().name().toLowerCase())
                        && f.get("dedup_enabled").asBoolean() == cfg.dedupEnabled()
                        && Double.compare(f.get("dedup_threshold").asDouble(), cfg.dedupThreshold()) == 0
                        && f.get("max_entities_per_chunk").asInt() == cfg.maxEntitiesPerChunk()
                        && f.get("extract_relations").asBoolean() == cfg.extractRelations()
                        && f.get("cross_chunk_relations").asBoolean() == cfg.crossChunkRelations()
                        && pyTypes.equals(cfg.entityTypes());
                if (!same) {
                    failures.add(name + ": field mismatch " + f);
                }
            } else {
                String py = c.get("message").asText();
                if (message == null) {
                    failures.add(name + ": python raised " + c.get("error_type").asText() + ", java accepted");
                } else if (py.startsWith("ExtractionConfig(method='llm') requires provider=")) {
                    assertEquals("ExtractionConfig(method='llm') requires llm=... (an LlmClient instance).", message);
                } else if (!py.equals(message)) {
                    failures.add(name + ": message\n  python: " + py + "\n  java:   " + message);
                }
            }
        }
        assertTrue(failures.isEmpty(), () -> String.join("\n", failures));
    }

    @Test
    void reprMatchesPython() throws IOException {
        JsonNode cs = cases("repr");
        List<String> failures = new ArrayList<>();
        for (JsonNode c : cs) {
            JsonNode v = c.get("value");
            if (v.isTextual() && !c.get("repr").asText().equals(PyRepr.str(v.asText()))) {
                failures.add("repr(str): python " + c.get("repr").asText() + " vs java " + PyRepr.str(v.asText()));
            }
            if (!c.get("repr").asText().equals(PyRepr.of(v))) {
                failures.add("repr: python " + c.get("repr").asText() + " vs java " + PyRepr.of(v));
            }
            if (!c.get("str").asText().equals(PyRepr.strOf(v))) {
                failures.add("str: python " + c.get("str").asText() + " vs java " + PyRepr.strOf(v));
            }
        }
        assertTrue(failures.isEmpty(), () -> failures.size() + " mismatches:\n" + String.join("\n", failures));
    }
}
