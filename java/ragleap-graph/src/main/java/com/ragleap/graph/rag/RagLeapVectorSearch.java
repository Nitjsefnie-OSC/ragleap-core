package com.ragleap.graph.rag;

import com.ragleap.graph.VectorSearch;
import com.ragleap.rag.RagLeap;
import com.ragleap.rag.vectorstore.SearchResult;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Lets GraphRetriever use a ragleap-rag RagLeap instance for its vector side: retrieve(query, topK, hybrid = true,
 * metadataFilter), like Python's rag.retrieve defaults. Each hit becomes a map with the keys of ragleap-rag's search
 * results.
 *
 * <p>ragleap-rag is an OPTIONAL dependency of ragleap-graph: add it to your own project to use this class.
 *
 * <p>The conversion and the error handling are tested with a stand-in retrieve function; the delegation to a real
 * RagLeap instance (of(RagLeap)) is not exercised against a live database here.
 */
public final class RagLeapVectorSearch implements VectorSearch {
    /** The one RagLeap method this class needs; of(RagLeap) passes rag::retrieve. */
    @FunctionalInterface
    public interface Retrieve {
        List<SearchResult> retrieve(String query, int topK, boolean hybrid, Map<String, Object> metadataFilter)
                throws SQLException;
    }

    private final Retrieve delegate;

    public RagLeapVectorSearch(Retrieve delegate) {
        this.delegate = Objects.requireNonNull(delegate, "delegate");
    }

    public static RagLeapVectorSearch of(RagLeap rag) {
        Objects.requireNonNull(rag, "rag");
        return new RagLeapVectorSearch(rag::retrieve);
    }

    @Override
    public List<Map<String, Object>> retrieve(String query, int topK, Map<String, Object> metadataFilter) {
        List<SearchResult> hits;
        try {
            hits = delegate.retrieve(query, topK, true, metadataFilter);
        } catch (SQLException e) {
            throw new IllegalStateException("vector retrieval failed: " + e.getMessage(), e);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (SearchResult h : hits) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("chunk_id", h.chunkId());
            m.put("text", h.text());
            m.put("similarity_score", h.similarityScore());
            m.put("document_id", h.documentId());
            m.put("document_name", h.documentName());
            m.put("chunk_index", h.chunkIndex());
            if (h.retrievalMethod() != null) {
                m.put("retrieval_method", h.retrievalMethod());
            }
            out.add(m);
        }
        return out;
    }
}
