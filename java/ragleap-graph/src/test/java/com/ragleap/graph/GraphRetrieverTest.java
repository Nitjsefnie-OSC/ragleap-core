package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Offline tests of GraphRetriever: ports of the Python tests (fakes, no services) plus a few extras. */
class GraphRetrieverTest {
    static final class FakeGraph implements GraphSearch {
        final List<String> queryEntities;
        final List<DocumentHit> docs;
        final List<RelatedEntity> related;
        final List<Object[]> extractCalls = new ArrayList<>();
        final List<Object[]> findDocsCalls = new ArrayList<>();
        final List<Object[]> searchRelatedCalls = new ArrayList<>();

        FakeGraph() {
            this(List.of("Acme Corp"), List.of(new DocumentHit("d3", "acme_contract.pdf", 1, 2.5, List.of("Acme Corp"))),
                    List.of(new RelatedEntity("neo4j", "Neo4j", "CO_OCCURS_WITH", 1)));
        }

        FakeGraph(List<String> queryEntities, List<DocumentHit> docs, List<RelatedEntity> related) {
            this.queryEntities = queryEntities;
            this.docs = docs;
            this.related = related;
        }

        @Override
        public List<String> extractQueryEntities(String query, int maxEntities, List<String> domainTerms) {
            extractCalls.add(new Object[] {query, maxEntities, domainTerms});
            return queryEntities;
        }

        @Override
        public List<DocumentHit> findDocumentsByEntities(List<String> names, String namespace, String userId, int limit) {
            findDocsCalls.add(new Object[] {names, namespace, userId, limit});
            return docs;
        }

        @Override
        public List<RelatedEntity> searchRelatedEntities(List<String> names, String namespace, String userId,
                int maxDepth, int limit) {
            searchRelatedCalls.add(new Object[] {names, namespace, userId, maxDepth, limit});
            return related;
        }
    }

    static final class FakeVector implements VectorSearch {
        final List<Map<String, Object>> chunks;
        Object[] calledWith;

        FakeVector() {
            this(List.of(chunk("c1", "d1", "q3_report.pdf", "Acme Corp reported strong Q3 revenue growth."),
                    chunk("c2", "d2", "press_release.pdf", "The new product line launched in partnership with Neo4j.")));
        }

        FakeVector(List<Map<String, Object>> chunks) {
            this.chunks = chunks;
        }

        @Override
        public List<Map<String, Object>> retrieve(String query, int topK, Map<String, Object> metadataFilter) {
            calledWith = new Object[] {query, topK, metadataFilter};
            return chunks.subList(0, Math.min(topK, chunks.size()));
        }
    }

    static Map<String, Object> chunk(String id, String doc, String name, String text) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("chunk_id", id);
        m.put("text", text);
        m.put("document_id", doc);
        m.put("document_name", name);
        m.put("chunk_index", 0);
        return m;
    }

    private static GraphRetrievalConfig graphOnly() {
        return GraphRetrievalConfig.builder().mode(GraphRetrievalConfig.Mode.GRAPH_ONLY).build();
    }

    @Test
    void configDefaults() {
        GraphRetrievalConfig c = GraphRetrievalConfig.defaults();
        assertEquals("hybrid", c.modeLabel());
        assertEquals(2, c.graphExpandDepth());
        assertEquals(10, c.maxGraphResults());
        assertEquals(10, c.maxQueryEntities());
        assertNull(c.domainTerms());
    }

    @Test
    void configRejectsBadValues() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> GraphRetrievalConfig.builder().mode("bogus").build());
        assertEquals("mode must be 'hybrid' or 'graph_only', got 'bogus'", e.getMessage());
        assertEquals("graph_expand_depth must be >= 1", assertThrows(IllegalArgumentException.class,
                () -> GraphRetrievalConfig.builder().graphExpandDepth(0).build()).getMessage());
        assertEquals("max_graph_results must be >= 1", assertThrows(IllegalArgumentException.class,
                () -> GraphRetrievalConfig.builder().maxGraphResults(0).build()).getMessage());
        assertEquals("max_query_entities must be >= 1", assertThrows(IllegalArgumentException.class,
                () -> GraphRetrievalConfig.builder().maxQueryEntities(0).build()).getMessage());
    }

    @Test
    void hybridCombinesChunksAndGraphContext() {
        RetrievalResult r = new GraphRetriever(new FakeGraph(), new FakeVector())
                .retrieve("What products has Acme Corp launched?", 2, null, null);
        assertEquals(2, r.chunks().size());
        assertEquals(List.of("Acme Corp"), r.queryEntities());
        assertEquals(1, r.graphContext().relatedDocuments().size());
        assertEquals(1, r.graphContext().relatedEntities().size());
        assertEquals("hybrid_vector_graph", r.retrievalMethod());
    }

    @Test
    void hybridPassesTheRightArgumentsToTheVectorSide() {
        FakeVector vector = new FakeVector();
        new GraphRetriever(new FakeGraph(), vector).retrieve("some query", 3, null, Map.of("tenant", "acme"));
        assertEquals("some query", vector.calledWith[0]);
        assertEquals(3, vector.calledWith[1]);
        assertEquals(Map.of("tenant", "acme"), vector.calledWith[2]);
    }

    @Test
    void citationsIncludeBothKinds() {
        RetrievalResult r = new GraphRetriever(new FakeGraph(), new FakeVector()).retrieve("query");
        long chunkCitations = r.citations().stream().filter(c -> c instanceof RetrievalResult.ChunkCitation).count();
        long pathCitations = r.citations().stream().filter(c -> c instanceof RetrievalResult.GraphPathCitation).count();
        assertEquals(2, chunkCitations);
        assertEquals(1, pathCitations);
        assertTrue(r.citations().get(0) instanceof RetrievalResult.ChunkCitation, "chunk citations come first");
    }

    @Test
    void noQueryEntitiesSkipsGraphCallsButStillReturnsChunks() {
        FakeGraph graph = new FakeGraph(List.of(), List.of(), List.of());
        RetrievalResult r = new GraphRetriever(graph, new FakeVector()).retrieve("vague query");
        assertTrue(r.queryEntities().isEmpty());
        assertTrue(r.graphContext().relatedDocuments().isEmpty());
        assertTrue(r.graphContext().relatedEntities().isEmpty());
        assertTrue(graph.findDocsCalls.isEmpty());
        assertTrue(graph.searchRelatedCalls.isEmpty());
        assertEquals(2, r.chunks().size());
    }

    @Test
    void graphOnlyNeverCallsTheVectorSide() {
        FakeVector vector = new FakeVector();
        RetrievalResult r = new GraphRetriever(new FakeGraph(), vector, graphOnly()).retrieve("Show all about Acme Corp");
        assertTrue(r.chunks().isEmpty());
        assertNull(vector.calledWith);
        assertEquals("graph_only", r.retrievalMethod());
    }

    @Test
    void graphOnlyStillPopulatesGraphContext() {
        RetrievalResult r = new GraphRetriever(new FakeGraph(), new FakeVector(), graphOnly()).retrieve("Acme Corp tickets");
        assertEquals(1, r.graphContext().relatedDocuments().size());
        assertEquals(1, r.graphContext().relatedEntities().size());
    }

    @Test
    void configValuesAreRoutedToTheGraphCalls() {
        FakeGraph graph = new FakeGraph();
        GraphRetrievalConfig config = GraphRetrievalConfig.builder().graphExpandDepth(5).maxGraphResults(3)
                .maxQueryEntities(4).domainTerms(List.of("ALARA", "dose limits")).build();
        new GraphRetriever(graph, new FakeVector(), config).retrieve("query about Acme Corp", 5, "acme-tenant", null);
        assertEquals(4, graph.extractCalls.get(0)[1]);
        assertEquals(List.of("ALARA", "dose limits"), graph.extractCalls.get(0)[2]);
        assertEquals(3, graph.findDocsCalls.get(0)[3]);
        assertEquals("acme-tenant", graph.findDocsCalls.get(0)[1]);
        assertNull(graph.findDocsCalls.get(0)[2], "the retriever passes no user id");
        assertEquals(5, graph.searchRelatedCalls.get(0)[3]);
        assertEquals(3, graph.searchRelatedCalls.get(0)[4]);
        assertEquals("acme-tenant", graph.searchRelatedCalls.get(0)[1]);
    }

    @Test
    void relatedDocumentsAreFlaggedWhenTheyOverlapVectorChunks() {
        FakeVector vector = new FakeVector(List.of(chunk("c1", "d1", "a.pdf", "Acme Corp news.")));
        FakeGraph graph = new FakeGraph(List.of("Acme Corp"),
                List.of(new DocumentHit("d1", "a.pdf", 1, 1.0, List.of("Acme Corp")),
                        new DocumentHit("d9", "b.pdf", 1, 1.0, List.of("Globex Corp"))), List.of());
        List<RetrievalResult.RelatedDocument> docs = new GraphRetriever(graph, vector).retrieve("test query")
                .graphContext().relatedDocuments();
        assertTrue(docs.get(0).alreadyInVectorResults());
        assertFalse(docs.get(1).alreadyInVectorResults());
    }

    @Test
    void missingDocumentNameBecomesUnknownButNullStaysNull() {
        Map<String, Object> noName = new LinkedHashMap<>();
        noName.put("text", "t");
        Map<String, Object> nullName = new LinkedHashMap<>();
        nullName.put("text", "t");
        nullName.put("document_name", null);
        RetrievalResult r = new GraphRetriever(new FakeGraph(), new FakeVector(List.of(noName, nullName)))
                .retrieve("query", 5, null, null);
        assertEquals("unknown document", ((RetrievalResult.ChunkCitation) r.citations().get(0)).documentName());
        assertNull(((RetrievalResult.ChunkCitation) r.citations().get(1)).documentName());
    }

    @Test
    void previewsAreCutAt150CodePointsWithAnEllipsisOnlyWhenLonger() {
        String exactly = "x".repeat(150);
        String longer = "a".repeat(149) + "\uD83D\uDE00" + "b";
        RetrievalResult r = new GraphRetriever(new FakeGraph(), new FakeVector(List.of(
                chunk("c1", "d1", "n", exactly), chunk("c2", "d2", "n", longer)))).retrieve("q", 5, null, null);
        assertEquals(exactly, ((RetrievalResult.ChunkCitation) r.citations().get(0)).textPreview());
        assertEquals("a".repeat(149) + "\uD83D\uDE00" + "...",
                ((RetrievalResult.ChunkCitation) r.citations().get(1)).textPreview());
    }

    @Test
    void domainTermsAreRoutedToEntityExtraction() {
        FakeGraph graph = new FakeGraph();
        new GraphRetriever(graph, new FakeVector(), GraphRetrievalConfig.builder()
                .domainTerms(List.of("ALARA", "dose limits")).build()).retrieve("query");
        assertEquals(List.of("ALARA", "dose limits"), graph.extractCalls.get(0)[2]);
    }

    @Test
    void hybridModeWithoutAVectorSideFailsAfterTheGraphLookups() {
        FakeGraph graph = new FakeGraph();
        GraphRetriever retriever = new GraphRetriever(graph, null);
        assertThrows(IllegalStateException.class, () -> retriever.retrieve("query"));
        assertEquals(1, graph.findDocsCalls.size());
        assertEquals(1, new GraphRetriever(new FakeGraph(), null, graphOnly()).retrieve("query").graphContext()
                .relatedDocuments().size());
    }

    @Test
    void aTextThatIsNotAStringIsRejected() {
        Map<String, Object> bad = new LinkedHashMap<>();
        bad.put("text", null);
        assertThrows(IllegalArgumentException.class, () -> new GraphRetriever(new FakeGraph(),
                new FakeVector(List.of(bad))).retrieve("query"));
    }

    @Test
    void anUnreachableGraphStillReturnsVectorChunks() {
        try (GraphIndex graph = new GraphIndex(new GraphConfig("http://localhost:1", "u", "p"))) {
            assertFalse(graph.isAvailable());
            RetrievalResult r = new GraphRetriever(graph, new FakeVector()).retrieve("What about Acme Corp?");
            assertEquals(2, r.chunks().size());
            assertTrue(r.graphContext().relatedDocuments().isEmpty());
            assertTrue(r.graphContext().relatedEntities().isEmpty());
        }
    }
}
