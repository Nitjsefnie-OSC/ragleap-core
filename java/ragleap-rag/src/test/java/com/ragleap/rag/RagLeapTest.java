package com.ragleap.rag;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ragleap.rag.cache.QueryEmbeddingCache;
import com.ragleap.rag.chunker.TextChunker;
import com.ragleap.rag.cost.CostTracker;
import com.ragleap.rag.generation.GenerationService;
import com.ragleap.rag.generation.ProviderConfig;
import com.ragleap.rag.ingestion.IngestionService;
import com.ragleap.rag.memory.ConversationMemory;
import com.ragleap.rag.memory.ConversationMessage;
import com.ragleap.rag.vectorstore.DocumentSummary;
import com.ragleap.rag.vectorstore.SearchResult;
import com.ragleap.rag.vectorstore.VectorBackend;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.function.Function;
import org.junit.jupiter.api.Test;

class RagLeapTest {
    static final class FakeBackend implements VectorBackend {
        final List<String> calls = Collections.synchronizedList(new ArrayList<>());
        final List<Map<String, Object>> chunkMetadata = Collections.synchronizedList(new ArrayList<>());
        final Map<String, String> filenames = new ConcurrentHashMap<>();

        @Override
        public void initSchema(int dimensions) {
            calls.add("initSchema:" + dimensions);
        }

        @Override
        public void insertDocument(String documentId, String filename, Map<String, Object> metadata) {
            calls.add("insertDocument:" + filename);
        }

        @Override
        public void insertChunk(String documentId, String documentName, int chunkIndex, String text,
                                Integer tokenCount, List<Double> embedding, Map<String, Object> metadata) {
            calls.add("insertChunk:" + documentName);
            chunkMetadata.add(metadata);
        }

        @Override
        public List<SearchResult> searchDense(List<Double> embedding, int topK, Map<String, Object> metadataFilter) {
            calls.add("dense:" + topK);
            return List.of();
        }

        @Override
        public List<SearchResult> searchHybrid(String queryText, List<Double> embedding, int topK,
                                               Map<String, Object> metadataFilter) {
            calls.add("hybrid:" + topK);
            return List.of();
        }

        @Override
        public List<DocumentSummary> listDocuments(int limit, int offset) {
            return List.of();
        }

        @Override
        public boolean deleteDocument(String documentId) {
            calls.add("delete:" + documentId);
            return filenames.remove(documentId) != null;
        }

        @Override
        public Optional<String> getDocumentFilename(String documentId) {
            return Optional.ofNullable(filenames.get(documentId));
        }
    }

    static final class FakeMemory extends ConversationMemory {
        final List<String> writes = Collections.synchronizedList(new ArrayList<>());

        FakeMemory() {
            super(null);
        }

        @Override
        public void addMessage(String sessionId, String role, String content) {
            writes.add(sessionId + ":" + role + ":" + content);
        }

        @Override
        public List<ConversationMessage> getHistory(String sessionId) {
            return List.of();
        }

        @Override
        public String buildHistoryPrompt(String sessionId) {
            return "";
        }

        @Override
        public void clearSession(String sessionId) {
            writes.add("clear:" + sessionId);
        }
    }

    private static final Function<String, List<Double>> EMBED = text -> List.of(1.0, 0.0);

    private static RagLeap facade(FakeBackend backend, Function<String, List<Double>> embed, boolean cache,
                                  FakeMemory memory, List<Consumer<Map<String, Object>>> onQuery) {
        GenerationService generator = new GenerationService(
                new ProviderConfig("openai", "key", "gpt-test", "http://localhost:1/v1"));
        IngestionService ingestion = new IngestionService(backend, embed, new TextChunker(), List.of(), List.of(), null);
        return new RagLeap(new RagLeap.Parts(null, "postgresql://unused", 2, backend, embed, "model-1", memory,
                generator, ingestion, cache ? new QueryEmbeddingCache(10) : null, new CostTracker(), null,
                List.of(), onQuery, List.of()));
    }

    @Test
    void configRequiresTheMandatoryArguments() {
        assertThrows(NullPointerException.class, () -> RagLeapConfig.builder(null, null, null).build());
        assertThrows(NullPointerException.class, () -> RagLeapConfig.builder("postgresql://x", null, null).build());
    }

    @Test
    void askAppologisesWhenTheEmbeddingFailsAndStoresNothing() throws Exception {
        FakeBackend backend = new FakeBackend();
        FakeMemory memory = new FakeMemory();
        RagLeap rag = facade(backend, text -> null, false, memory, List.of());
        AskResult r = rag.ask("anything", AskOptions.builder().sessionId("s1").build());
        assertEquals("Sorry, I couldn't process your question (embedding failed).", r.answer());
        assertTrue(r.sources().isEmpty());
        assertTrue(r.citations().isEmpty());
        assertEquals(0, r.chunksSent());
        assertNull(r.usage());
        assertNull(r.cost());
        assertNull(r.providerUsed());
        assertTrue(memory.writes.isEmpty());
        assertTrue(backend.calls.isEmpty());
    }

    @Test
    void askStreamAppologisesWhenTheEmbeddingFails() throws Exception {
        RagLeap rag = facade(new FakeBackend(), text -> null, false, new FakeMemory(), List.of());
        List<String> pieces = new ArrayList<>();
        rag.askStream("anything", AskOptions.defaults(), pieces::add);
        assertEquals(List.of("Sorry, I couldn't process your question (embedding failed)."), pieces);
    }

    @Test
    void cacheStatsCountHitsAndMissesAndDisabledMeansZeros() throws Exception {
        AtomicInteger embedCalls = new AtomicInteger();
        Function<String, List<Double>> counting = text -> {
            embedCalls.incrementAndGet();
            return List.of(1.0, 0.0);
        };
        RagLeap cached = facade(new FakeBackend(), counting, true, new FakeMemory(), List.of());
        cached.retrieve("same query");
        cached.retrieve("same query");
        assertEquals(1, embedCalls.get());
        CacheInfo info = cached.cacheStats();
        assertEquals(1, info.hits());
        assertEquals(1, info.misses());
        assertEquals(1, info.size());
        assertTrue(info.enabled());

        embedCalls.set(0);
        RagLeap uncached = facade(new FakeBackend(), counting, false, new FakeMemory(), List.of());
        uncached.retrieve("same query");
        uncached.retrieve("same query");
        assertEquals(2, embedCalls.get());
        CacheInfo off = uncached.cacheStats();
        assertEquals(0, off.hits());
        assertEquals(0, off.size());
        assertFalse(off.enabled());
    }

    @Test
    void retrieveSearchesHybridByDefaultAndFiresTheQueryEvent() throws Exception {
        FakeBackend backend = new FakeBackend();
        List<Map<String, Object>> events = new ArrayList<>();
        RagLeap rag = facade(backend, EMBED, false, new FakeMemory(), List.of(events::add));
        rag.retrieve("q");
        assertEquals(List.of("hybrid:5"), backend.calls);
        Map<String, Object> ev = events.get(0);
        assertEquals(Boolean.FALSE, ev.get("rerank"));
        assertEquals(Boolean.FALSE, ev.get("streaming"));
        assertEquals(0, ev.get("chunks_retrieved"));
        assertTrue(ev.containsKey("query_rewrite"));
        assertNull(ev.get("query_rewrite"));
    }

    @Test
    void updateAndDeleteDocument() throws Exception {
        FakeBackend backend = new FakeBackend();
        backend.filenames.put("old-1", "doc.txt");
        RagLeap rag = facade(backend, EMBED, false, new FakeMemory(), List.of());

        IllegalArgumentException missing = assertThrows(IllegalArgumentException.class,
                () -> rag.updateDocument("nope", "text", null));
        assertEquals("No document found with id nope", missing.getMessage());
        assertTrue(backend.calls.isEmpty());

        assertTrue(rag.updateDocument("old-1", "New text content here", null).chunksStored() >= 1);
        assertEquals("delete:old-1", backend.calls.get(0));
        assertEquals("insertDocument:doc.txt", backend.calls.get(1));
        assertEquals("insertChunk:doc.txt", backend.calls.get(2));

        backend.calls.clear();
        rag.updateDocument("unknown-id", "Renamed text content", "renamed.txt");
        assertEquals("delete:unknown-id", backend.calls.get(0));
        assertEquals("insertDocument:renamed.txt", backend.calls.get(1));
        assertFalse(rag.deleteDocument("unknown-id"));
    }

    @Test
    void batchKeepsOrderIsolatesFailuresAndKeepsFileMetadata() throws Exception {
        FakeBackend backend = new FakeBackend();
        RagLeap rag = facade(backend, EMBED, false, new FakeMemory(), List.of());
        Map<String, Object> meta = new HashMap<>();
        meta.put("team", "sales");
        List<BatchResult> results = rag.ingestBatch(List.of(
                BatchItem.file("a.txt", "first document text".getBytes(), meta),
                BatchItem.file("empty.txt", new byte[0]),
                BatchItem.file("c.txt", "third document text".getBytes())));
        assertEquals(3, results.size());
        assertTrue(results.get(0).success());
        assertFalse(results.get(1).success());
        assertTrue(results.get(1).error() != null && !results.get(1).error().isEmpty());
        assertTrue(results.get(2).success());
        assertNull(results.get(2).error());
        assertTrue(backend.chunkMetadata.stream().anyMatch(m -> "sales".equals(m.get("team"))));
        assertTrue(rag.ingestBatch(List.of()).isEmpty());
    }

    @Test
    void evaluateRejectsAnEmptyCaseList() {
        RagLeap rag = facade(new FakeBackend(), EMBED, false, new FakeMemory(), List.of());
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> rag.evaluate(List.of(), AskOptions.defaults()));
        assertEquals("evaluate() requires at least one test case.", e.getMessage());
    }
}
