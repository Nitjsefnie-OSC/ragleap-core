package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Runs against a real Neo4j test server; the vector side is a stand-in. Uses its own unique namespace and removes its data. */
@EnabledIfEnvironmentVariable(named = "NEO4J_HTTP_URL", matches = ".+")
class LiveRetrievalTest {
    private static GraphConfig config() {
        return new GraphConfig(System.getenv("NEO4J_HTTP_URL"),
                System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
    }

    private static List<Map<String, Object>> chunks(String text) {
        List<Map<String, Object>> list = new ArrayList<>();
        list.add(Map.of("text", text));
        return list;
    }

    @Test
    void retrievalOverARealGraph() {
        String ns = "ragleap_graph_java_retrieval_" + UUID.randomUUID();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                assertTrue(graph.upsertDocument("doc-1", "Doc One",
                        chunks("Acme Corp announced a partnership with Globex Industries."), ns).success());
                assertTrue(graph.upsertDocument("doc-2", "Doc Two",
                        chunks("Initech Systems licensed software from Globex Industries."), ns).success());
                String query = "What do Acme Corp and Globex Industries share?";
                assertEquals(2, graph.extractQueryEntities(query).size());

                RetrievalResult graphOnly = new GraphRetriever(graph, null, GraphRetrievalConfig.builder()
                        .mode(GraphRetrievalConfig.Mode.GRAPH_ONLY).build()).retrieve(query, 5, ns, null);
                assertEquals("graph_only", graphOnly.retrievalMethod());
                assertTrue(graphOnly.chunks().isEmpty());
                Set<String> ids = new HashSet<>();
                int doc1Matches = 0;
                for (RetrievalResult.RelatedDocument d : graphOnly.graphContext().relatedDocuments()) {
                    ids.add(d.document().documentId());
                    assertFalse(d.alreadyInVectorResults());
                    if (d.document().documentId().equals("doc-1")) {
                        doc1Matches = d.document().matchedEntities();
                    }
                }
                assertEquals(Set.of("doc-1", "doc-2"), ids);
                assertEquals(2, doc1Matches, "doc-1 mentions both query entities");
                assertEquals(graphOnly.graphContext().relatedEntities().size(), graphOnly.citations().size());

                Object[] seen = new Object[2];
                VectorSearch vector = (q, k, f) -> {
                    seen[0] = k;
                    seen[1] = f;
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("chunk_id", "c1");
                    c.put("text", "Initech Systems licensed software from Globex Industries.");
                    c.put("document_id", "doc-2");
                    c.put("document_name", "Doc Two");
                    c.put("chunk_index", 0);
                    return List.of(c);
                };
                RetrievalResult hybrid = new GraphRetriever(graph, vector).retrieve(query, 3, ns, Map.of("tenant", "x"));
                assertEquals("hybrid_vector_graph", hybrid.retrievalMethod());
                assertEquals(3, seen[0]);
                assertEquals(Map.of("tenant", "x"), seen[1]);
                for (RetrievalResult.RelatedDocument d : hybrid.graphContext().relatedDocuments()) {
                    assertEquals(d.document().documentId().equals("doc-2"), d.alreadyInVectorResults());
                }
                assertTrue(hybrid.citations().get(0) instanceof RetrievalResult.ChunkCitation);
            } finally {
                direct.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
            }
            assertEquals(0L, ((Number) direct.run("MATCH (n) WHERE n.namespace = $ns RETURN count(n) AS cnt",
                    Map.of("ns", ns)).get(0).get("cnt")).longValue());
        }
    }
}
