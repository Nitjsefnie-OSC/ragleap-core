package com.ragleap.rag;

import com.fasterxml.jackson.databind.JsonNode;
import com.ragleap.rag.generation.Citation;
import com.ragleap.rag.generation.Usage;
import com.ragleap.rag.structured.ValidationMethod;
import java.util.List;

/**
 * The answer to a question. The generation fields come from the provider; queryRewrite is set only when a
 * rewrite strategy was used, cost is null when the embedding failed, and guardrailBlocked is null when no output
 * guardrails are configured.
 */
public record AskResult(String answer, List<String> sources, List<Citation> citations, String providerUsed,
                        String modelUsed, Usage usage, int chunksSent, JsonNode structured, Boolean structuredValid,
                        String structuredEnforcement, ValidationMethod structuredValidationMethod,
                        QueryRewriteInfo queryRewrite, CostInfo cost, Boolean guardrailBlocked) {
}
