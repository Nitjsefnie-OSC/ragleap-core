package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Runs against a real Neo4j test server with a scripted model client (no real LLM is called). Every test uses its own
 * unique namespace and removes its data.
 */
@EnabledIfEnvironmentVariable(named = "NEO4J_HTTP_URL", matches = ".+")
class LiveExtractionTest {
    private static final String CHUNK_A = "Acme Corp hired Alice Smith last year.";
    private static final String CHUNK_B = "ACME Corp. also works with Bob Lee on projects.";

    private static GraphConfig config() {
        return new GraphConfig(System.getenv("NEO4J_HTTP_URL"),
                System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
    }

    private static final class Scripted implements LlmClient {
        private final Map<String, String> entities = Map.of(
                CHUNK_A, "{\"entities\":[{\"name\":\"Acme Corp\",\"type\":\"ORG\"},"
                        + "{\"name\":\"Alice Smith\",\"type\":\"PERSON\"}]}",
                CHUNK_B, "{\"entities\":[{\"name\":\"ACME Corp.\",\"type\":\"ORG\"},"
                        + "{\"name\":\"Bob Lee\",\"type\":\"PERSON\"}]}");
        private final Map<String, String> relations = Map.of(
                CHUNK_A, "{\"relations\":[{\"subject\":\"Alice Smith\",\"relation_type\":\"works_at\","
                        + "\"object\":\"Acme Corp\"}]}",
                CHUNK_B, "{\"relations\":[{\"subject\":\"Bob Lee\",\"relation_type\":\"works_at\","
                        + "\"object\":\"ACME Corp.\"}]}");

        @Override
        public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
                JsonNode responseFormat, double temperature) {
            boolean entity = responseFormat == LlmEntityExtractor.SCHEMA;
            return LlmExtractorTest.ok((entity ? entities : relations).getOrDefault(chunkText,
                    entity ? "{\"entities\":[]}" : "{\"relations\":[]}"));
        }
    }

    private static long count(CypherRunner r, String cypher, String ns) {
        return ((Number) r.run(cypher, Map.of("ns", ns)).get(0).get("cnt")).longValue();
    }

    private static long nodes(CypherRunner r, String label, String ns) {
        return count(r, "MATCH (n:" + label + " {namespace: $ns}) RETURN count(n) AS cnt", ns);
    }

    private static long relatesAs(CypherRunner r, String ns) {
        return count(r, "MATCH (a:Entity {namespace: $ns})-[r:RELATES_AS]->(b:Entity {namespace: $ns}) "
                + "RETURN count(r) AS cnt", ns);
    }

    private static long withType(CypherRunner r, String type, String ns) {
        return count(r, "MATCH (e:Entity {namespace: $ns}) WHERE e.entity_type = '" + type
                + "' RETURN count(e) AS cnt", ns);
    }

    private static Set<String> relationWeights(CypherRunner r, String ns) {
        Set<String> out = new HashSet<>();
        for (Map<String, Object> row : r.run("MATCH (rw:RelationWeight {namespace: $ns}) RETURN rw.subject AS subject, "
                + "rw.relation_type AS relation_type, rw.object AS object", Map.of("ns", ns))) {
            out.add(row.get("subject") + "|" + row.get("relation_type") + "|" + row.get("object"));
        }
        return out;
    }

    private static List<Map<String, Object>> chunks() {
        List<Map<String, Object>> list = new ArrayList<>();
        list.add(Map.of("text", CHUNK_A));
        list.add(Map.of("text", CHUNK_B));
        return list;
    }

    private static void cleanup(CypherRunner r, String ns) {
        r.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
    }

    @Test
    void llmExtractionWithDedupLandsInNeo4j() {
        String ns = "ragleap_graph_java_extraction_" + UUID.randomUUID();
        ExtractionConfig cfg = ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(new Scripted())
                .extractRelations(true).dedupEnabled(true).build();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config(), cfg)) {
            try {
                assertTrue(graph.healthCheck());
                UpsertSummary first = graph.upsertDocument("doc-1", "Extraction Test", chunks(), ns);
                assertTrue(first.success(), String.valueOf(first));
                assertEquals(3, first.entitiesIndexed());
                assertEquals(2, first.relationshipsIndexed());
                assertEquals(2, first.relationsIndexed());

                assertEquals(3L, nodes(direct, "Entity", ns), "Acme Corp and ACME Corp. must be merged");
                assertEquals(2L, withType(direct, "PERSON", ns));
                assertEquals(1L, withType(direct, "ORG", ns));
                assertEquals(2L, nodes(direct, "RelationWeight", ns));
                assertEquals(2L, relatesAs(direct, ns));
                assertEquals(Set.of("alice smith|WORKS_AT|acme corp.", "bob lee|WORKS_AT|acme corp."),
                        relationWeights(direct, ns));

                assertEquals(2, graph.findEntitiesByType("person", ns, null, 25).size());
                assertEquals(1, graph.findDocumentsByEntities(List.of("Alice Smith"), ns, null, 25).size());
                assertEquals(3, graph.documentEntities("doc-1", ns, null).size());

                UpsertSummary second = graph.upsertDocument("doc-1", "Extraction Test", chunks(), ns);
                assertEquals(first, second, "re-upserting the same document must give the same summary");
                assertEquals(3L, nodes(direct, "Entity", ns));
                assertEquals(1L, nodes(direct, "Document", ns));
                assertEquals(2L, nodes(direct, "RelationWeight", ns));
                assertEquals(2L, relatesAs(direct, ns));
            } finally {
                cleanup(direct, ns);
            }
            assertEquals(0L, count(direct, "MATCH (n) WHERE n.namespace = $ns RETURN count(n) AS cnt", ns));
        }
    }

    @Test
    void failedExtractionWritesNothing() {
        String ns = "ragleap_graph_java_extraction_" + UUID.randomUUID();
        LlmClient failing = (s, q, t, d, f, temp) -> new LlmResult(null, "boom", null, false, null);
        ExtractionConfig cfg = ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(failing).build();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config(), cfg)) {
            try {
                ExtractionException e = assertThrows(ExtractionException.class,
                        () -> graph.upsertDocument("doc-1", "T", chunks(), ns));
                assertEquals("RuntimeError", e.pythonType());
                assertEquals(0L, count(direct, "MATCH (n) WHERE n.namespace = $ns RETURN count(n) AS cnt", ns));
            } finally {
                cleanup(direct, ns);
            }
        }
    }
}
