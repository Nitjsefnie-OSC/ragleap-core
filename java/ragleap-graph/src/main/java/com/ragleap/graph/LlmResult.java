package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * What an extractor needs from one model call: the keys of the dict Python's generate_answer returns
 * (provider_used, answer, structured, structured_valid, structured_enforcement). providerUsed is null when every
 * provider failed.
 */
public record LlmResult(String providerUsed, String answer, JsonNode structured, Boolean structuredValid,
        String structuredEnforcement) {
}
