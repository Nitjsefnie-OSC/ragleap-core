package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Compares upsertDocument with extraction against the real Python code: every Cypher statement and parameter, every
 * model call (prompt, text, schema, temperature), the summary, and the error when extraction fails.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class UpsertExtractionParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    record LogCall(String kind, String query, String text, String documentName, String systemPrompt,
            double temperature) {
    }

    static final class Scripted implements LlmClient {
        final JsonNode script;
        final List<LogCall> log = new ArrayList<>();

        Scripted(JsonNode script) {
            this.script = script;
        }

        @Override
        public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
                JsonNode responseFormat, double temperature) {
            boolean entity = responseFormat == LlmEntityExtractor.SCHEMA;
            String kind = entity ? "entity" : "relation";
            log.add(new LogCall(kind, query, chunkText, documentName, systemPrompt, temperature));
            JsonNode table = script.get(kind);
            if (table != null && table.has(chunkText)) {
                return toResult(table.get(chunkText));
            }
            return LlmExtractorTest.ok(entity ? "{\"entities\":[]}" : "{\"relations\":[]}");
        }
    }

    private static String text(JsonNode n) {
        return n == null || n.isNull() ? null : n.asText();
    }

    private static List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        n.forEach(e -> out.add(e.asText()));
        return out;
    }

    private static LlmResult toResult(JsonNode r) {
        return new LlmResult(text(r.get("provider_used")), text(r.get("answer")), r.get("structured"),
                r.hasNonNull("structured_valid") ? r.get("structured_valid").asBoolean() : null,
                text(r.get("structured_enforcement")));
    }

    private static ExtractionConfig config(JsonNode spec, LlmClient client) {
        ExtractionConfig.Builder b = ExtractionConfig.builder();
        String method = spec.has("method") ? spec.get("method").asText() : "llm";
        if (method.equals("llm")) {
            b.method(ExtractionConfig.Method.LLM).llm(client);
        }
        if (spec.has("entity_types")) {
            b.entityTypes(strings(spec.get("entity_types")));
        }
        if (spec.has("max_entities_per_chunk")) {
            b.maxEntitiesPerChunk(spec.get("max_entities_per_chunk").asInt());
        }
        if (spec.has("dedup_enabled")) {
            b.dedupEnabled(spec.get("dedup_enabled").asBoolean());
        }
        if (spec.has("dedup_threshold")) {
            b.dedupThreshold(spec.get("dedup_threshold").asDouble());
        }
        if (spec.has("extract_relations")) {
            b.extractRelations(spec.get("extract_relations").asBoolean());
        }
        if (spec.has("cross_chunk_relations")) {
            b.crossChunkRelations(spec.get("cross_chunk_relations").asBoolean());
        }
        if (spec.has("relation_ontology")) {
            Map<String, ExtractionConfig.Ontology> ont = new LinkedHashMap<>();
            spec.get("relation_ontology").fields().forEachRemaining(e -> ont.put(e.getKey(),
                    new ExtractionConfig.Ontology(strings(e.getValue().get(0)), strings(e.getValue().get(1)))));
            b.relationOntology(ont);
        }
        return b.build();
    }

    private static String brief(UpsertParityTest.Call c) {
        String s = c.cypher().substring(0, Math.min(60, c.cypher().length())) + " | " + c.params();
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }

    @Test
    void upsertWithExtractionMatchesPython() throws IOException {
        JsonNode cases = MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"),
                "upsert_extraction_cases.json").toFile());
        assertTrue(cases.size() >= 38, "fixture count: " + cases.size());
        List<String> bad = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            Scripted client = new Scripted(c.get("script"));
            UpsertParityTest.Recorder rec = new UpsertParityTest.Recorder(c.get("old_pairs"), c.get("old_relations"));
            GraphIndex graph = new GraphIndex(rec, AuditSink.NOOP, s -> { }, config(c.get("config"), client));
            rec.calls.clear();
            JsonNode a = c.get("args");
            List<Map<String, Object>> chunks = MAPPER.convertValue(a.get("chunks"),
                    new TypeReference<List<Map<String, Object>>>() { });
            List<String> terms = a.get("domain_terms").isNull() ? null : strings(a.get("domain_terms"));

            UpsertSummary s = null;
            String raised = null;
            String message = null;
            try {
                s = graph.upsertDocument(a.get("document_id").asText(), text(a.get("title")), chunks,
                        text(a.get("namespace")), text(a.get("user_id")), a.get("max_entities").asInt(),
                        a.get("max_pairs").asInt(), terms);
            } catch (ExtractionException e) {
                raised = e.pythonType();
                message = e.getMessage();
            }

            String expRaise = text(c.get("raises"));
            if (!Objects.equals(expRaise, raised)) {
                bad.add(name + ": raises " + expRaise + " (python) vs " + raised + " (java: " + message + ")");
            } else if (expRaise != null) {
                if (!Objects.equals(text(c.get("message")), message)) {
                    bad.add(name + ": message\n  python: " + text(c.get("message")) + "\n  java:   " + message);
                }
            } else {
                JsonNode es = c.get("summary");
                if (s.success() != es.get("success").asBoolean()
                        || s.entitiesIndexed() != es.get("entities_indexed").asInt()
                        || s.relationshipsIndexed() != es.get("relationships_indexed").asInt()
                        || s.relationsIndexed() != es.get("relations_indexed").asInt() || s.error() != null) {
                    bad.add(name + ": summary differs, java=" + s + " python=" + es);
                }
            }

            List<UpsertParityTest.Call> expected = new ArrayList<>();
            for (JsonNode call : c.get("calls")) {
                expected.add(new UpsertParityTest.Call(call.get("cypher").asText(),
                        UpsertParityTest.canon(call.get("params"))));
            }
            expected = UpsertParityTest.normalize(expected);
            List<UpsertParityTest.Call> actual = UpsertParityTest.normalize(rec.calls);
            if (actual.size() != expected.size()) {
                bad.add(name + ": " + actual.size() + " statements, python sent " + expected.size());
            } else {
                for (int i = 0; i < actual.size(); i++) {
                    if (!actual.get(i).equals(expected.get(i))) {
                        bad.add(name + ": statement " + i + " differs\n  java:   " + brief(actual.get(i))
                                + "\n  python: " + brief(expected.get(i)));
                        break;
                    }
                }
            }

            JsonNode exp = c.get("llm_calls");
            if (exp.size() != client.log.size()) {
                bad.add(name + ": " + client.log.size() + " model calls, python made " + exp.size());
                continue;
            }
            for (int i = 0; i < exp.size(); i++) {
                JsonNode pc = exp.get(i);
                LogCall jc = client.log.get(i);
                boolean same = pc.get("kind").asText().equals(jc.kind())
                        && pc.get("query").asText().equals(jc.query())
                        && pc.get("text").asText().equals(jc.text())
                        && pc.get("document_name").asText().equals(jc.documentName())
                        && pc.get("system_prompt").asText().equals(jc.systemPrompt())
                        && pc.get("temperature").asDouble() == jc.temperature();
                if (!same) {
                    bad.add(name + ": model call " + i + " differs\n  python: " + pc.get("kind").asText() + " | "
                            + pc.get("query").asText() + "\n  java:   " + jc.kind() + " | " + jc.query());
                    break;
                }
            }
        }
        assertTrue(bad.isEmpty(), () -> cases.size() + " scenarios, " + bad.size() + " problems:\n"
                + String.join("\n", bad));
    }
}
