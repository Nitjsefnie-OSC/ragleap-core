package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Offline tests of upsertDocument with extraction (scripted model answers, recording runner). */
class UpsertExtractionTest {
    static final class Statements implements CypherRunner {
        final List<String> cypher = new ArrayList<>();

        @Override
        public List<Map<String, Object>> run(String c, Map<String, Object> p) {
            cypher.add(c);
            return List.of();
        }
    }

    static final class Scripted implements LlmClient {
        final List<String> entityTexts = new ArrayList<>();
        final List<String> relationTexts = new ArrayList<>();
        final Map<String, String> entities;
        final Map<String, String> relations;

        Scripted(Map<String, String> entities, Map<String, String> relations) {
            this.entities = entities;
            this.relations = relations;
        }

        @Override
        public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
                JsonNode responseFormat, double temperature) {
            boolean entity = responseFormat == LlmEntityExtractor.SCHEMA;
            (entity ? entityTexts : relationTexts).add(chunkText);
            return LlmExtractorTest.ok((entity ? entities : relations).getOrDefault(chunkText,
                    entity ? "{\"entities\":[]}" : "{\"relations\":[]}"));
        }
    }

    private static List<Map<String, Object>> chunks(String... texts) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (String t : texts) {
            list.add(Map.of("text", t));
        }
        return list;
    }

    private static GraphIndex index(Statements rec, ExtractionConfig cfg) {
        GraphIndex g = new GraphIndex(rec, AuditSink.NOOP, s -> { }, cfg);
        rec.cypher.clear();
        return g;
    }

    private static ExtractionConfig.Builder llm(LlmClient c) {
        return ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(c);
    }

    private static final String ALICE_ACME = "{\"entities\":[{\"name\":\"Alice\",\"type\":\"PERSON\"},"
            + "{\"name\":\"Acme\",\"type\":\"ORG\"}]}";

    @Test
    void llmUpsertCountsEntitiesPairsAndRelations() {
        Scripted c = new Scripted(Map.of("t1", ALICE_ACME), Map.of("t1",
                "{\"relations\":[{\"subject\":\"Alice\",\"relation_type\":\"works_at\",\"object\":\"Acme\"}]}"));
        GraphIndex g = index(new Statements(), llm(c).extractRelations(true).build());
        UpsertSummary s = g.upsertDocument("d1", "T", chunks("t1"));
        assertTrue(s.success(), String.valueOf(s));
        assertEquals(2, s.entitiesIndexed());
        assertEquals(1, s.relationshipsIndexed());
        assertEquals(1, s.relationsIndexed());
    }

    @Test
    void blankChunksMakeNoModelCalls() {
        Scripted c = new Scripted(Map.of("t1", ALICE_ACME), Map.of());
        GraphIndex g = index(new Statements(), llm(c).build());
        g.upsertDocument("d1", "T", List.of(Map.of("text", ""), Map.of("text", "  \n"), Map.of("other", "x"),
                Map.of("text", "  t1  ")));
        assertEquals(List.of("t1"), c.entityTexts);
    }

    @Test
    void extractionErrorsPropagateAndWriteNothing() {
        LlmClient failing = (s, q, t, d, f, temp) -> new LlmResult(null, "boom", null, false, null);
        Statements rec = new Statements();
        GraphIndex g = index(rec, llm(failing).build());
        ExtractionException e = assertThrows(ExtractionException.class, () -> g.upsertDocument("d1", "T", chunks("t1")));
        assertEquals("RuntimeError", e.pythonType());
        assertTrue(rec.cypher.isEmpty(), "nothing may be written when extraction fails");
    }

    @Test
    void dedupMergesNearDuplicateNames() {
        Map<String, String> answers = Map.of(
                "t1", "{\"entities\":[{\"name\":\"Acme Corp\",\"type\":\"ORG\"}]}",
                "t2", "{\"entities\":[{\"name\":\"ACME Corp.\",\"type\":\"ORG\"}]}");
        UpsertSummary off = index(new Statements(), llm(new Scripted(answers, Map.of())).build())
                .upsertDocument("d1", "T", chunks("t1", "t2"));
        UpsertSummary on = index(new Statements(), llm(new Scripted(answers, Map.of())).dedupEnabled(true).build())
                .upsertDocument("d1", "T", chunks("t1", "t2"));
        assertEquals(2, off.entitiesIndexed());
        assertEquals(1, on.entitiesIndexed());
    }

    @Test
    void crossChunkPassUsesTheFullTextAndEveryEntity() {
        Scripted c = new Scripted(Map.of("t1", ALICE_ACME, "t2", "{\"entities\":[{\"name\":\"Bob\",\"type\":\"PERSON\"}]}"),
                Map.of());
        GraphIndex g = index(new Statements(), llm(c).extractRelations(true).crossChunkRelations(true).build());
        g.upsertDocument("d1", "T", chunks("t1", "t2"));
        // Chunk t2 knows only one entity, and Python makes no relation call for fewer than two known entities.
        assertEquals(List.of("t1", "t1\n\nt2"), c.relationTexts);
    }

    @Test
    void regexConfigNeverCallsAModel() {
        GraphIndex g = index(new Statements(), ExtractionConfig.regex());
        UpsertSummary s = g.upsertDocument("d1", "T", chunks("Acme Corp announced a deal with Globex Industries."));
        assertTrue(s.success());
        assertTrue(s.entitiesIndexed() > 0);
        assertEquals(ExtractionConfig.Method.REGEX, g.extractionConfig().method());
    }
}
