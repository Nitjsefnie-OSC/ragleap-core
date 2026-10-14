package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Offline tests of the LLM extractors with scripted model answers (hand-written expectations). */
class LlmExtractorTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    static final class Scripted implements LlmClient {
        final List<String> queries = new ArrayList<>();
        LlmResult next;

        Scripted(LlmResult next) {
            this.next = next;
        }

        @Override
        public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
                JsonNode responseFormat, double temperature) {
            queries.add(query);
            return next;
        }
    }

    static LlmResult ok(String json) {
        try {
            return new LlmResult("fake", json, MAPPER.readTree(json), true, "native");
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static ExtractionConfig config(LlmClient c, List<String> types, int max) {
        return ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(c).entityTypes(types)
                .maxEntitiesPerChunk(max).build();
    }

    @Test
    void instructionsMatchThePythonText() {
        Scripted c = new Scripted(ok("{\"entities\":[]}"));
        new LlmEntityExtractor(config(c, List.of("ORG", "PERSON"), 25)).extract("text", List.of("Widget", "Gizmo"));
        assertEquals("Extract all named entities from the given text. Where an entity fits one of these categories, "
                + "use that category as its type: ORG, PERSON. Use your own judgment for entities that do not fit "
                + "any of these. Pay particular attention to these known domain terms if present: Widget, Gizmo.",
                c.queries.get(0));
        Scripted rc = new Scripted(ok("{\"relations\":[]}"));
        new LlmRelationExtractor(config(rc, null, 25)).extract("text", List.of("A", "B"), List.of("T"), true, null);
        assertEquals("Identify relationships between these known entities: A, B. Pay particular attention to these "
                + "known domain terms if present: T. The text may refer to a known entity using a pronoun or vague "
                + "phrase instead of its name (e.g. 'it', 'the company', 'he', 'she', 'they'). When this happens, "
                + "resolve the reference to the correct known entity name and use that name as the subject or object.",
                rc.queries.get(0));
    }

    @Test
    void providerFailureMessageUsesPythonNone() {
        Scripted c = new Scripted(new LlmResult(null, null, null, null, null));
        ExtractionException e = assertThrows(ExtractionException.class,
                () -> new LlmEntityExtractor(config(c, null, 25)).extract("text"));
        assertEquals("RuntimeError", e.pythonType());
        assertEquals("LLM entity extraction failed on all configured providers: None", e.getMessage());
    }

    @Test
    void nullNameBecomesNoneAndTheCapCountsBlankSlots() {
        Scripted c = new Scripted(ok("{\"entities\":[{\"name\":null,\"type\":\"X\"},{\"name\":\"\",\"type\":\"X\"},"
                + "{\"name\":\"Acme\",\"type\":\"ORG\"}]}"));
        List<ExtractedEntity> out = new LlmEntityExtractor(config(c, null, 2)).extract("text");
        assertEquals(List.of(new ExtractedEntity("None", "X")), out);
    }

    @Test
    void typesOutsideTheListBecomeUnknown() {
        Scripted c = new Scripted(ok("{\"entities\":[{\"name\":\"A\",\"type\":\"ORG\"},{\"name\":\"B\",\"type\":\"Org\"}]}"));
        List<ExtractedEntity> out = new LlmEntityExtractor(config(c, List.of("ORG"), 25)).extract("text");
        assertEquals(List.of(new ExtractedEntity("A", "ORG"), new ExtractedEntity("B", "UNKNOWN")), out);
    }

    @Test
    void malformedAnswerMentionsEnforcementAndRepr() {
        Scripted c = new Scripted(new LlmResult("fake", "oops", null, false, "json_object"));
        ExtractionException e = assertThrows(ExtractionException.class,
                () -> new LlmEntityExtractor(config(c, null, 25)).extract("text"));
        assertEquals("ValueError", e.pythonType());
        assertEquals("Malformed extraction response from provider 'fake' (enforcement=json_object): 'oops'",
                e.getMessage());
    }

    @Test
    void relationsAreFilteredAndKeepTheModelsCasing() {
        Scripted c = new Scripted(ok("{\"relations\":["
                + "{\"subject\":\"acme corp\",\"relation_type\":\" partnered_with \",\"object\":\"GLOBEX\"},"
                + "{\"subject\":\"Acme Corp\",\"relation_type\":\"X\",\"object\":\"acme corp\"},"
                + "{\"subject\":\"Nobody\",\"relation_type\":\"X\",\"object\":\"Globex\"}]}"));
        List<ExtractedRelation> out = new LlmRelationExtractor(config(c, null, 25))
                .extract("text", List.of("Acme Corp", "Globex"));
        assertEquals(List.of(new ExtractedRelation("acme corp", "PARTNERED_WITH", "GLOBEX")), out);
    }

    @Test
    void ontologyFiltersOnlyConstrainedTypes() {
        Scripted c = new Scripted(ok("{\"relations\":["
                + "{\"subject\":\"Alice\",\"relation_type\":\"WORKS_AT\",\"object\":\"Acme\"},"
                + "{\"subject\":\"Acme\",\"relation_type\":\"WORKS_AT\",\"object\":\"Alice\"},"
                + "{\"subject\":\"Acme\",\"relation_type\":\"REPORTED\",\"object\":\"Alice\"}]}"));
        ExtractionConfig cfg = ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(c)
                .entityTypes(List.of("PERSON", "ORG"))
                .relationOntology(Map.of("WORKS_AT",
                        new ExtractionConfig.Ontology(List.of("PERSON"), List.of("ORG")))).build();
        List<ExtractedRelation> out = new LlmRelationExtractor(cfg).extract("text", List.of("Alice", "Acme"), null,
                false, Map.of("alice", "PERSON", "acme", "ORG"));
        assertEquals(List.of(new ExtractedRelation("Alice", "WORKS_AT", "Acme"),
                new ExtractedRelation("Acme", "REPORTED", "Alice")), out);
    }

    @Test
    void fewerThanTwoKnownEntitiesMakeNoCall() {
        Scripted c = new Scripted(ok("{\"relations\":[]}"));
        assertTrue(new LlmRelationExtractor(config(c, null, 25)).extract("text", List.of("A")).isEmpty());
        assertTrue(c.queries.isEmpty());
    }
}
