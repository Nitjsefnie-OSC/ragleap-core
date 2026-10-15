package com.ragleap.graph.rag;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ragleap.rag.vectorstore.SearchResult;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Tests the conversion and error handling with a stand-in retrieve function (no database). */
class RagLeapVectorSearchTest {
    @Test
    void searchResultsBecomeChunkMapsAndHybridIsRequested() {
        List<Object[]> calls = new ArrayList<>();
        RagLeapVectorSearch search = new RagLeapVectorSearch((q, k, hybrid, f) -> {
            calls.add(new Object[] {q, k, hybrid, f});
            return List.of(new SearchResult("c1", "text one", 0.5, "d1", "doc.pdf", 2),
                    new SearchResult("c2", "text two", 0.25, "d2", "b.pdf", 0, "hybrid_rrf"));
        });
        List<Map<String, Object>> out = search.retrieve("query", 3, Map.of("tenant", "acme"));

        assertEquals("query", calls.get(0)[0]);
        assertEquals(3, calls.get(0)[1]);
        assertEquals(true, calls.get(0)[2]);
        assertEquals(Map.of("tenant", "acme"), calls.get(0)[3]);

        Map<String, Object> first = new LinkedHashMap<>();
        first.put("chunk_id", "c1");
        first.put("text", "text one");
        first.put("similarity_score", 0.5);
        first.put("document_id", "d1");
        first.put("document_name", "doc.pdf");
        first.put("chunk_index", 2);
        assertEquals(first, out.get(0));
        assertTrue(!out.get(0).containsKey("retrieval_method"));
        assertEquals("hybrid_rrf", out.get(1).get("retrieval_method"));
    }

    @Test
    void aDatabaseErrorBecomesAnIllegalStateExceptionWithTheCause() {
        RagLeapVectorSearch search = new RagLeapVectorSearch((q, k, hybrid, f) -> {
            throw new SQLException("db down");
        });
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> search.retrieve("q", 5, null));
        assertEquals("vector retrieval failed: db down", e.getMessage());
        assertTrue(e.getCause() instanceof SQLException);
    }

    @Test
    void nullArgumentsAreRejected() {
        assertThrows(NullPointerException.class, () -> new RagLeapVectorSearch(null));
        assertThrows(NullPointerException.class, () -> RagLeapVectorSearch.of(null));
    }
}
