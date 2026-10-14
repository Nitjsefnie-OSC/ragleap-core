package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * The one thing LLM extraction needs from a model: answer a query about a single chunk of text, with the answer
 * constrained to a JSON schema. Implement it with any model client; an adapter over ragleap-rag's
 * GenerationService is planned as an optional add-on.
 */
@FunctionalInterface
public interface LlmClient {
    /**
     * @param systemPrompt   fixed instructions for this kind of extraction
     * @param query          the extraction instruction
     * @param chunkText      the text to extract from (sent as one context chunk)
     * @param documentName   label of that chunk
     * @param responseFormat JSON schema the answer must follow
     * @param temperature    sampling temperature (always 0.0 for extraction)
     */
    LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
            JsonNode responseFormat, double temperature);
}
