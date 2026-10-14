package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.StringJoiner;
import java.util.logging.Logger;

/**
 * Identifies typed relations between an already-known set of entities (port of
 * ragleap_graph.extraction.LLMRelationExtractor), on top of an LlmClient. NOT live-verified: tested with scripted
 * model answers only.
 */
public final class LlmRelationExtractor {
    private static final Logger LOG = Logger.getLogger(LlmRelationExtractor.class.getName());

    static final String SYSTEM_PROMPT = "You identify relationships between named entities in text. Only "
            + "identify relationships explicitly stated or clearly implied by the "
            + "text - never invent relationships not supported by it. Both the "
            + "subject and object of every relation must be exactly one of the "
            + "provided known entity names - do not introduce new entity names.";

    static final JsonNode SCHEMA = LlmParsing.schema("""
            {"type":"object","properties":{"relations":{"type":"array","items":{"type":"object",
            "properties":{"subject":{"type":"string","description":"Name of the subject entity. Must exactly match one of the provided known entity names."},
            "relation_type":{"type":"string","description":"Relationship type in UPPER_SNAKE_CASE, e.g. REPORTED, LAUNCHED, PARTNERED_WITH, ACQUIRED."},
            "object":{"type":"string","description":"Name of the object entity. Must exactly match one of the provided known entity names."}},
            "required":["subject","relation_type","object"]}}},"required":["relations"]}
            """);

    private final ExtractionConfig config;
    private final LlmClient llm;

    public LlmRelationExtractor(ExtractionConfig config) {
        if (config.method() != ExtractionConfig.Method.LLM) {
            throw new IllegalArgumentException("LLMRelationExtractor requires ExtractionConfig(method='llm')");
        }
        this.config = config;
        this.llm = config.llm();
    }

    public List<ExtractedRelation> extract(String text, List<String> knownEntities) {
        return extract(text, knownEntities, null, false, null);
    }

    /**
     * Relations between knownEntities as they appear in text. Returns an empty list without calling the model when
     * the text is blank or fewer than two entities are known. resolveReferences asks the model to resolve pronouns
     * (used by the cross-chunk pass). entityTypes is {lower-cased entity name: type}; it is used only when the
     * config has a relation ontology: a relation whose type is constrained by the ontology is dropped (with a
     * warning) unless its subject and object types are allowed.
     */
    public List<ExtractedRelation> extract(String text, List<String> knownEntities, List<String> domainTerms,
            boolean resolveReferences, Map<String, String> entityTypes) {
        if (text == null || PyText.strip(text).isEmpty() || knownEntities.size() < 2) {
            return List.of();
        }
        String instruction = buildInstruction(knownEntities, domainTerms, resolveReferences);
        LlmResult result = llm.generate(SYSTEM_PROMPT, instruction, text, "relation_extraction_input", SCHEMA, 0.0);
        if (result == null || result.providerUsed() == null) {
            throw new ExtractionException("RuntimeError", "LLM relation extraction failed on all configured providers: "
                    + LlmParsing.none(result == null ? null : result.answer()));
        }
        List<ExtractedRelation> relations = parse(result, knownEntities);
        if (!config.relationOntology().isEmpty() && entityTypes != null && !entityTypes.isEmpty()) {
            relations = filterByOntology(relations, entityTypes);
        }
        return relations;
    }

    String buildInstruction(List<String> knownEntities, List<String> domainTerms, boolean resolveReferences) {
        String base = "Identify relationships between these known entities: " + String.join(", ", knownEntities) + ".";
        if (domainTerms != null && !domainTerms.isEmpty()) {
            base += " Pay particular attention to these known domain terms if present: "
                    + String.join(", ", domainTerms) + ".";
        }
        if (resolveReferences) {
            base += " The text may refer to a known entity using a pronoun or vague "
                    + "phrase instead of its name (e.g. 'it', 'the company', 'he', 'she', "
                    + "'they'). When this happens, resolve the reference to the correct "
                    + "known entity name and use that name as the subject or object.";
        }
        return base;
    }

    List<ExtractedRelation> parse(LlmResult result, List<String> knownEntities) {
        JsonNode raw = LlmParsing.listField(result, "relations");
        if (raw == null) {
            throw new ExtractionException("ValueError", "Malformed relation extraction response from provider '"
                    + result.providerUsed() + "': " + LlmParsing.reprOrNone(result.answer()));
        }
        Set<String> knownLower = new HashSet<>();
        for (String e : knownEntities) {
            knownLower.add(PyText.lower(e));
        }
        List<ExtractedRelation> relations = new ArrayList<>();
        for (JsonNode item : LlmParsing.iterItems(raw)) {
            String subject = PyText.strip(LlmParsing.str(item, "subject", ""));
            String relationType = pyUpper(PyText.strip(LlmParsing.str(item, "relation_type", "")));
            String obj = PyText.strip(LlmParsing.str(item, "object", ""));
            if (subject.isEmpty() || relationType.isEmpty() || obj.isEmpty()) {
                continue;
            }
            if (!knownLower.contains(PyText.lower(subject)) || !knownLower.contains(PyText.lower(obj))) {
                continue;
            }
            if (PyText.lower(subject).equals(PyText.lower(obj))) {
                continue;
            }
            relations.add(new ExtractedRelation(subject, relationType, obj));
        }
        return relations;
    }

    /** Python str.upper(): full Unicode case mapping, not locale dependent. */
    static String pyUpper(String s) {
        return s.toUpperCase(Locale.ROOT);
    }

    private List<ExtractedRelation> filterByOntology(List<ExtractedRelation> relations, Map<String, String> entityTypes) {
        List<ExtractedRelation> kept = new ArrayList<>();
        for (ExtractedRelation rel : relations) {
            ExtractionConfig.Ontology allowed = config.relationOntology().get(rel.relationType());
            if (allowed == null) {
                kept.add(rel);
                continue;
            }
            String subjType = entityTypes.getOrDefault(PyText.lower(rel.subject()), "UNKNOWN");
            String objType = entityTypes.getOrDefault(PyText.lower(rel.object()), "UNKNOWN");
            if (allowed.subjectTypes().contains(subjType) && allowed.objectTypes().contains(objType)) {
                kept.add(rel);
            } else {
                LOG.warning("Dropping relation violating ontology: (" + rel.subject() + ": " + subjType + ") -["
                        + rel.relationType() + "]-> (" + rel.object() + ": " + objType + "). Allowed subject types: "
                        + pyList(allowed.subjectTypes()) + ", allowed object types: " + pyList(allowed.objectTypes())
                        + ".");
            }
        }
        return kept;
    }

    private static String pyList(List<String> items) {
        StringJoiner j = new StringJoiner(", ", "[", "]");
        for (String s : items) {
            j.add(PyRepr.str(s));
        }
        return j.toString();
    }
}
