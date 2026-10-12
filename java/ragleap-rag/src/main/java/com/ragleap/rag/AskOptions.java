package com.ragleap.rag;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;

/**
 * Options for {@link RagLeap#ask} and {@link RagLeap#askStream}, with the Python defaults
 * (top 5, hybrid search on, no session). Streaming ignores responseFormat, queryRewrite and multiQueryN.
 */
public record AskOptions(int topK, Double temperature, String systemPrompt, Integer maxTokens, boolean hybrid,
                         String sessionId, Map<String, Object> metadataFilter, JsonNode responseFormat,
                         QueryRewrite queryRewrite, int multiQueryN) {

    public static AskOptions defaults() {
        return builder().build();
    }

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private int topK = 5;
        private Double temperature;
        private String systemPrompt;
        private Integer maxTokens;
        private boolean hybrid = true;
        private String sessionId;
        private Map<String, Object> metadataFilter;
        private JsonNode responseFormat;
        private QueryRewrite queryRewrite;
        private int multiQueryN = 3;

        private Builder() {
        }

        public Builder topK(int v) {
            this.topK = v;
            return this;
        }

        public Builder temperature(Double v) {
            this.temperature = v;
            return this;
        }

        public Builder systemPrompt(String v) {
            this.systemPrompt = v;
            return this;
        }

        public Builder maxTokens(Integer v) {
            this.maxTokens = v;
            return this;
        }

        public Builder hybrid(boolean v) {
            this.hybrid = v;
            return this;
        }

        public Builder sessionId(String v) {
            this.sessionId = v;
            return this;
        }

        public Builder metadataFilter(Map<String, Object> v) {
            this.metadataFilter = v;
            return this;
        }

        public Builder responseFormat(JsonNode v) {
            this.responseFormat = v;
            return this;
        }

        public Builder queryRewrite(QueryRewrite v) {
            this.queryRewrite = v;
            return this;
        }

        public Builder multiQueryN(int v) {
            this.multiQueryN = v;
            return this;
        }

        public AskOptions build() {
            return new AskOptions(topK, temperature, systemPrompt, maxTokens, hybrid, sessionId, metadataFilter,
                    responseFormat, queryRewrite, multiQueryN);
        }
    }
}
