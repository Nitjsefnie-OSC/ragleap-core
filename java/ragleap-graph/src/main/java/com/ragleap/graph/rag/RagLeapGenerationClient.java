package com.ragleap.graph.rag;

import com.fasterxml.jackson.databind.JsonNode;
import com.ragleap.graph.LlmClient;
import com.ragleap.graph.LlmResult;
import com.ragleap.rag.generation.GenerationResult;
import com.ragleap.rag.generation.GenerationService;
import com.ragleap.rag.generation.ProviderConfig;
import com.ragleap.rag.vectorstore.SearchResult;
import java.util.List;
import java.util.Objects;

/**
 * Lets LLM extraction use ragleap-rag's GenerationService (provider chain, structured output) as its model. This is
 * the Java counterpart of how the Python extractors build a GenerationService from a ProviderConfig.
 *
 * <p>ragleap-rag is an OPTIONAL dependency of ragleap-graph: add {@code io.github.antonyrag:ragleap-rag} to your own
 * project to use this class. Without it, nothing else in ragleap-graph needs it.
 *
 * <p>NOT live-verified against real model providers. It is tested against a local fake HTTP server only (the real
 * GenerationService request and response handling runs, the model's answer is scripted).
 */
public final class RagLeapGenerationClient implements LlmClient {
    private final GenerationService service;

    /** Uses the given service as is (fallbacks, token limit and context budget are yours to choose). */
    public RagLeapGenerationClient(GenerationService service) {
        this.service = Objects.requireNonNull(service, "service");
    }

    /** A service for one provider with the defaults the Python extractors use (temperature 0.0, no fallbacks). */
    public static RagLeapGenerationClient of(ProviderConfig primary) {
        Objects.requireNonNull(primary, "primary");
        return new RagLeapGenerationClient(new GenerationService(primary, List.of(), 0.0, 1024, 12000,
                GenerationService.DEFAULT_SYSTEM_PROMPT));
    }

    @Override
    public LlmResult generate(String systemPrompt, String query, String chunkText, String documentName,
            JsonNode responseFormat, double temperature) {
        SearchResult chunk = new SearchResult(null, chunkText, 0.0, null, documentName, 0);
        GenerationResult r = service.generateAnswer(query, List.of(chunk), temperature, null, null, null,
                systemPrompt, responseFormat);
        return new LlmResult(r.providerUsed(), r.answer(), r.structured(), r.structuredValid(),
                r.structuredEnforcement());
    }
}
