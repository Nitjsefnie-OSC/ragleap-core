package com.ragleap.graph;

import java.util.List;
import java.util.Map;

/**
 * The vector side of GraphRetriever: returns chunks as maps with the keys of ragleap-rag's search results (chunk_id,
 * text, similarity_score, document_id, document_name, chunk_index, and retrieval_method for hybrid search). Maps keep
 * "key missing" and "key present but null" apart, which the citation code treats differently, as Python does.
 */
@FunctionalInterface
public interface VectorSearch {
    List<Map<String, Object>> retrieve(String query, int topK, Map<String, Object> metadataFilter);
}
