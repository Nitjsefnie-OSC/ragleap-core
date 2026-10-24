package com.ragleap.vectorstores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ragleap.rag.vectorstore.DocumentSummary;
import com.ragleap.rag.vectorstore.SearchResult;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Live check against a real OpenSearch (k-NN plugin, security disabled). Skipped unless
 * RAGLEAP_VS_LIVE_OPENSEARCH_URL is set (for example http://127.0.0.1:9201 for a throwaway container). Uses its own
 * index names and drops them at the end. Never point it at a production cluster.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_VS_LIVE_OPENSEARCH_URL", matches = ".+")
class OpenSearchLiveTest {

    private static String describe(List<SearchResult> rs) {
        StringBuilder sb = new StringBuilder();
        for (SearchResult s : rs) {
            sb.append(s.text()).append('=').append(s.similarityScore()).append(' ');
        }
        return sb.toString();
    }

    private static void dropIndex(String url, String name) {
        try {
            HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create(url + "/" + name)).DELETE().build(),
                    HttpResponse.BodyHandlers.discarding());
        } catch (Exception e) {
            System.out.println("LIVE opensearch cleanup warning: " + e.getMessage());
        }
    }

    @Test
    void liveRoundTrip() throws Exception {
        String url = System.getenv("RAGLEAP_VS_LIVE_OPENSEARCH_URL");
        String sfx = UUID.randomUUID().toString().substring(0, 8);
        String index = "live_idx_" + sfx;
        OpenSearchBackend be = new OpenSearchBackend(url, index, null, false, null, null);
        try {
            be.initSchema(3);
            be.initSchema(3);   // the index exists now: reused
            IllegalStateException mismatch = assertThrows(IllegalStateException.class, () -> be.initSchema(4));
            System.out.println("LIVE opensearch dimension mismatch message: " + mismatch.getMessage());

            be.insertDocument("d1", "a.txt", Map.of("k", "v"));
            be.insertDocument("doc-2:x", "b.txt", Map.of());
            be.insertChunk("d1", "a.txt", 0, "alpha", 1, List.of(1.0, 0.0, 0.0), Map.of("page", 1));
            be.insertChunk("d1", "a.txt", 1, "beta", 1, List.of(0.0, 1.0, 0.0), Map.of("page", 2));
            be.insertChunk("d1", "a.txt", 2, "gamma", 1, List.of(-1.0, 0.0, 0.0), Map.of());
            be.insertChunk("doc-2:x", "b.txt", 0, "delta", 1, List.of(0.9, 0.1, 0.0), Map.of());

            List<SearchResult> all = be.searchDense(List.of(1.0, 0.0, 0.0), 10, null);
            System.out.println("LIVE opensearch scores (query [1,0,0]): " + describe(all));
            System.out.println("LIVE opensearch first chunk id: " + (all.isEmpty() ? "none" : all.get(0).chunkId()));
            assertEquals(4, all.size());
            assertEquals(List.of("alpha", "delta", "beta", "gamma"), all.stream().map(SearchResult::text).toList());
            assertEquals(1.0, all.get(0).similarityScore(), 0.0005);
            assertEquals(0.9969, all.get(1).similarityScore(), 0.001);
            assertEquals(0.5, all.get(2).similarityScore(), 0.0005);
            assertEquals(0.0, all.get(3).similarityScore(), 0.0005);
            assertEquals("doc-2:x", all.get(1).documentId());

            List<SearchResult> d1 = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("document_id", "d1"));
            System.out.println("LIVE opensearch filter document_id=d1: " + describe(d1));
            assertEquals(3, d1.size());
            List<SearchResult> odd = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("document_id", "doc-2:x"));
            assertEquals(List.of("delta"), odd.stream().map(SearchResult::text).toList());
            List<SearchResult> byIndex = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("chunk_index", 0));
            System.out.println("LIVE opensearch filter chunk_index=0: " + describe(byIndex));
            assertEquals(2, byIndex.size());
            List<SearchResult> custom = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("page", 1));
            System.out.println("LIVE opensearch custom metadata filter page=1 matched: " + custom.size()
                    + " (chunks were inserted with metadata page=1 on alpha)");
            List<SearchResult> unknown = be.searchDense(List.of(1.0, 0.0, 0.0), 10, Map.of("no_such_field", "x"));
            System.out.println("LIVE opensearch unknown filter field matched: " + unknown.size());

            List<DocumentSummary> docs = be.listDocuments(10, 0);
            Map<String, Long> counts = new HashMap<>();
            for (DocumentSummary d : docs) {
                counts.put(d.documentId(), d.chunkCount());
                assertNotNull(d.uploadedAt());
            }
            System.out.println("LIVE opensearch chunk counts: " + counts + " | order: "
                    + docs.stream().map(DocumentSummary::documentId).toList());
            assertEquals(3L, counts.get("d1"));
            assertEquals(1L, counts.get("doc-2:x"));
            assertEquals(Map.of("k", "v"), docs.stream().filter(d -> d.documentId().equals("d1")).findFirst().get().metadata());

            assertEquals("a.txt", be.getDocumentFilename("d1").orElseThrow());
            assertTrue(be.getDocumentFilename("nope").isEmpty());

            assertTrue(be.deleteDocument("d1"));
            assertFalse(be.deleteDocument("ghost"));
            List<SearchResult> after = be.searchDense(List.of(1.0, 0.0, 0.0), 10, null);
            assertEquals(List.of("delta"), after.stream().map(SearchResult::text).toList());
            assertTrue(be.getDocumentFilename("d1").isEmpty());
        } finally {
            dropIndex(url, index);
            dropIndex(url, index + "_documents");
        }
    }
}
