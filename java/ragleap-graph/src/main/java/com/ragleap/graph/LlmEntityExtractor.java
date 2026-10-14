package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * LLM-based entity extraction (port of ragleap_graph.extraction.LLMEntityExtractor), on top of an LlmClient. NOT
 * live-verified: tested with scripted model answers only.
 */
public final class LlmEntityExtractor {
    static final String SYSTEM_PROMPT = "You extract named entities from text. Only extract entities "
            + "explicitly present in the given text \u2014 never invent or infer "
            + "entities that aren't stated. Respond using the required structure "
            + "only; do not include any commentary outside it.";

    static final JsonNode SCHEMA = LlmParsing.schema("""
            {"type":"object","properties":{"entities":{"type":"array","items":{"type":"object",
            "properties":{"name":{"type":"string","description":"The entity's name exactly as it appears in the text."},
            "type":{"type":"string","description":"Entity category, e.g. PERSON, ORG, PRODUCT, DATE, LOCATION, or a domain-specific type."}},
            "required":["name","type"]}}},"required":["entities"]}
            """);

    private final ExtractionConfig config;
    private final LlmClient llm;

    public LlmEntityExtractor(ExtractionConfig config) {
        if (config.method() != ExtractionConfig.Method.LLM) {
            throw new IllegalArgumentException("LLMEntityExtractor requires ExtractionConfig(method='llm')");
        }
        this.config = config;
        this.llm = config.llm();
    }

    public List<ExtractedEntity> extract(String text) {
        return extract(text, null);
    }

    /**
     * Extracts entities from text. domainTerms is extra guidance for the model. Throws ExtractionException when every
     * provider failed or the answer is malformed (Python: RuntimeError / ValueError).
     */
    public List<ExtractedEntity> extract(String text, List<String> domainTerms) {
        if (text == null || PyText.strip(text).isEmpty()) {
            return List.of();
        }
        String instruction = buildInstruction(domainTerms);
        LlmResult result = llm.generate(SYSTEM_PROMPT, instruction, text, "extraction_input", SCHEMA, 0.0);
        if (result == null || result.providerUsed() == null) {
            throw new ExtractionException("RuntimeError", "LLM entity extraction failed on all configured providers: "
                    + LlmParsing.none(result == null ? null : result.answer()));
        }
        return parse(result);
    }

    String buildInstruction(List<String> domainTerms) {
        String base = "Extract all named entities from the given text.";
        if (!config.entityTypes().isEmpty()) {
            base += " Where an entity fits one of these categories, use that category as its type: "
                    + String.join(", ", config.entityTypes())
                    + ". Use your own judgment for entities that do not fit any of these.";
        }
        if (domainTerms == null || domainTerms.isEmpty()) {
            return base;
        }
        return base + " Pay particular attention to these known domain terms if present: "
                + String.join(", ", domainTerms) + ".";
    }

    List<ExtractedEntity> parse(LlmResult result) {
        JsonNode raw = LlmParsing.listField(result, "entities");
        if (raw == null) {
            throw new ExtractionException("ValueError", "Malformed extraction response from provider '"
                    + result.providerUsed() + "' (enforcement=" + LlmParsing.none(result.structuredEnforcement())
                    + "): " + LlmParsing.reprOrNone(result.answer()));
        }
        List<ExtractedEntity> entities = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (JsonNode item : LlmParsing.sliceItems(raw, config.maxEntitiesPerChunk())) {
            String name = PyText.strip(LlmParsing.str(item, "name", ""));
            if (name.isEmpty()) {
                continue;
            }
            if (!seen.add(PyText.lower(name))) {
                continue;
            }
            String rawType = LlmParsing.str(item, "type", "UNKNOWN");
            String type = !config.entityTypes().isEmpty() && !config.entityTypes().contains(rawType)
                    ? "UNKNOWN" : rawType;
            entities.add(new ExtractedEntity(name, type));
        }
        return entities;
    }
}
