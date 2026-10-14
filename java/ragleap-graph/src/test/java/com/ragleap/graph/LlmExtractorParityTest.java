package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertTrue;

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

/** Compares the LLM extractors with the real Python classes (scripted model answers): prompts, parsing, errors. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class LlmExtractorParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    record Call(String systemPrompt, String query, String chunkText, String documentName, JsonNode schema,
            double temperature) {
    }

    static final class Recording implements LlmClient {
        final List<Call> calls = new ArrayList<>();
        LlmResult result;

        @Override
        public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
                JsonNode responseFormat, double temperature) {
            calls.add(new Call(systemPrompt, query, chunkText, documentName, responseFormat, temperature));
            return result;
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

    private static ExtractionConfig config(JsonNode spec, Recording client) {
        ExtractionConfig.Builder b = ExtractionConfig.builder();
        String method = spec != null && spec.has("method") ? spec.get("method").asText() : "llm";
        if (method.equals("llm")) {
            b.method(ExtractionConfig.Method.LLM).llm(client);
        }
        if (spec != null && spec.has("entity_types")) {
            b.entityTypes(strings(spec.get("entity_types")));
        }
        if (spec != null && spec.has("max_entities_per_chunk")) {
            b.maxEntitiesPerChunk(spec.get("max_entities_per_chunk").asInt());
        }
        if (spec != null && spec.has("relation_ontology")) {
            Map<String, ExtractionConfig.Ontology> ont = new LinkedHashMap<>();
            spec.get("relation_ontology").fields().forEachRemaining(e -> ont.put(e.getKey(),
                    new ExtractionConfig.Ontology(strings(e.getValue().get(0)), strings(e.getValue().get(1)))));
            b.relationOntology(ont);
        }
        return b.build();
    }

    private static JsonNode load() throws IOException {
        return MAPPER.readTree(Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"), "extraction_llm_cases.json")
                .toFile()).get("cases");
    }

    private void compare(String kind) throws IOException {
        List<String> failures = new ArrayList<>();
        int count = 0;
        for (JsonNode c : load()) {
            if (!c.get("kind").asText().equals(kind)) {
                continue;
            }
            count++;
            String name = c.get("name").asText();
            Recording client = new Recording();
            client.result = toResult(c.get("result"));
            boolean entity = kind.equals("entity");

            Object extractor = null;
            String ctorError = null;
            try {
                ExtractionConfig cfg = config(c.get("config"), client);
                extractor = entity ? new LlmEntityExtractor(cfg) : new LlmRelationExtractor(cfg);
            } catch (IllegalArgumentException e) {
                ctorError = e.getMessage();
            }
            if (c.has("ctor_raises")) {
                if (ctorError == null || !"ValueError".equals(c.get("ctor_raises").asText())
                        || !c.get("ctor_message").asText().equals(ctorError)) {
                    failures.add(name + ": constructor error mismatch: " + ctorError);
                }
                continue;
            }
            if (ctorError != null) {
                failures.add(name + ": java constructor threw: " + ctorError);
                continue;
            }

            List<List<String>> output = new ArrayList<>();
            String raised = null;
            String message = null;
            try {
                if (entity) {
                    for (ExtractedEntity e : ((LlmEntityExtractor) extractor).extract(c.get("text").asText(),
                            c.hasNonNull("domain_terms") ? strings(c.get("domain_terms")) : null)) {
                        output.add(List.of(e.name(), e.type()));
                    }
                } else {
                    Map<String, String> types = null;
                    if (c.hasNonNull("entity_types")) {
                        types = new LinkedHashMap<>();
                        for (var it = c.get("entity_types").fields(); it.hasNext();) {
                            var e = it.next();
                            types.put(e.getKey(), e.getValue().asText());
                        }
                    }
                    for (ExtractedRelation r : ((LlmRelationExtractor) extractor).extract(c.get("text").asText(),
                            strings(c.get("known_entities")),
                            c.hasNonNull("domain_terms") ? strings(c.get("domain_terms")) : null,
                            c.has("resolve_references") && c.get("resolve_references").asBoolean(), types)) {
                        output.add(List.of(r.subject(), r.relationType(), r.object()));
                    }
                }
            } catch (ExtractionException e) {
                raised = e.pythonType();
                message = e.getMessage();
            }

            String expRaise = text(c.get("raises"));
            if (!Objects.equals(expRaise, raised)) {
                failures.add(name + ": raises " + expRaise + " (python) vs " + raised + " (java: " + message + ")");
            } else if (expRaise != null) {
                if (!Objects.equals(text(c.get("message")), message)) {
                    failures.add(name + ": message\n  python: " + text(c.get("message")) + "\n  java:   " + message);
                }
            } else {
                List<List<String>> expected = new ArrayList<>();
                c.get("output").forEach(row -> expected.add(strings(row)));
                if (!expected.equals(output)) {
                    failures.add(name + ": output\n  python: " + expected + "\n  java:   " + output);
                }
            }

            JsonNode expCalls = c.get("calls");
            if (expCalls.size() != client.calls.size()) {
                failures.add(name + ": call count " + expCalls.size() + " (python) vs " + client.calls.size() + " (java)");
                continue;
            }
            for (int i = 0; i < expCalls.size(); i++) {
                JsonNode pc = expCalls.get(i);
                Call jc = client.calls.get(i);
                JsonNode chunk = pc.get("chunks").get(0);
                boolean same = pc.get("chunks").size() == 1
                        && Objects.equals(pc.get("query").asText(), jc.query())
                        && Objects.equals(chunk.get("text").asText(), jc.chunkText())
                        && Objects.equals(chunk.get("document_name").asText(), jc.documentName())
                        && chunk.get("chunk_index").asInt() == 0
                        && pc.get("response_format").equals(jc.schema())
                        && pc.get("temperature").asDouble() == jc.temperature()
                        && c.get("ctor").get("system_prompt").asText().equals(jc.systemPrompt())
                        && c.get("ctor").get("default_temperature").asDouble() == jc.temperature();
                if (!same) {
                    failures.add(name + ": call " + i + " differs\n  python query: " + pc.get("query").asText()
                            + "\n  java query:   " + jc.query());
                }
            }
        }
        assertTrue(count >= (entity(kind) ? 55 : 35), "fixture count for " + kind + ": " + count);
        assertTrue(failures.isEmpty(), () -> failures.size() + " mismatches:\n" + String.join("\n", failures));
    }

    private static boolean entity(String kind) {
        return kind.equals("entity");
    }

    @Test
    void entityExtractorMatchesPython() throws IOException {
        compare("entity");
    }

    @Test
    void relationExtractorMatchesPython() throws IOException {
        compare("relation");
    }
}
