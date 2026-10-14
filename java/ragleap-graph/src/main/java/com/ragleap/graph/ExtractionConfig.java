package com.ragleap.graph;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Configuration for entity extraction and deduplication (port of ragleap_graph.extraction.ExtractionConfig).
 * Validation happens in build(), in the same order and with the same messages as Python, except that the "provider"
 * message names llm(...) instead of a ragleap.ProviderConfig. An empty entityTypes list or relationOntology map
 * counts as "not set", as in Python.
 */
public final class ExtractionConfig {
    public enum Method { REGEX, LLM }

    /** Allowed subject and object entity types of one relation type. */
    public record Ontology(List<String> subjectTypes, List<String> objectTypes) {
    }

    private final Method method;
    private final LlmClient llm;
    private final boolean dedupEnabled;
    private final double dedupThreshold;
    private final int maxEntitiesPerChunk;
    private final boolean extractRelations;
    private final boolean crossChunkRelations;
    private final List<String> entityTypes;
    private final Map<String, Ontology> relationOntology;

    private ExtractionConfig(Builder b) {
        this.method = b.method;
        this.llm = b.llm;
        this.dedupEnabled = b.dedupEnabled;
        this.dedupThreshold = b.dedupThreshold;
        this.maxEntitiesPerChunk = b.maxEntitiesPerChunk;
        this.extractRelations = b.extractRelations;
        this.crossChunkRelations = b.crossChunkRelations;
        this.entityTypes = b.entityTypes == null ? List.of() : List.copyOf(b.entityTypes);
        this.relationOntology = b.relationOntology == null ? Map.of()
                : Collections.unmodifiableMap(new LinkedHashMap<>(b.relationOntology));
        validate();
    }

    private void validate() {
        if (extractRelations && method != Method.LLM) {
            throw new IllegalArgumentException("extract_relations=True requires method='llm' - relation "
                    + "extraction has no regex equivalent, unlike entity extraction.");
        }
        if (crossChunkRelations && !extractRelations) {
            throw new IllegalArgumentException("cross_chunk_relations=True requires extract_relations=True - "
                    + "the cross-chunk pass reuses the same LLM relation extractor.");
        }
        if (!relationOntology.isEmpty() && entityTypes.isEmpty()) {
            throw new IllegalArgumentException("relation_ontology=... requires entity_types=... - an ontology "
                    + "constrains relation_type against entity types, so without a "
                    + "known set of entity types every entity would be 'UNKNOWN' and "
                    + "nothing could ever be validated against anything real.");
        }
        if (method == Method.LLM && llm == null) {
            throw new IllegalArgumentException("ExtractionConfig(method='llm') requires llm=... "
                    + "(an LlmClient instance).");
        }
        if (!(dedupThreshold > 0.0 && dedupThreshold <= 1.0)) {
            throw new IllegalArgumentException("dedup_threshold must be in (0.0, 1.0]");
        }
        if (maxEntitiesPerChunk < 1) {
            throw new IllegalArgumentException("max_entities_per_chunk must be >= 1");
        }
    }

    public static Builder builder() {
        return new Builder();
    }

    /** The default: regex extraction, no dedup, no LLM calls. */
    public static ExtractionConfig regex() {
        return builder().build();
    }

    public Method method() {
        return method;
    }

    public LlmClient llm() {
        return llm;
    }

    public boolean dedupEnabled() {
        return dedupEnabled;
    }

    public double dedupThreshold() {
        return dedupThreshold;
    }

    public int maxEntitiesPerChunk() {
        return maxEntitiesPerChunk;
    }

    public boolean extractRelations() {
        return extractRelations;
    }

    public boolean crossChunkRelations() {
        return crossChunkRelations;
    }

    /** Empty when not set. */
    public List<String> entityTypes() {
        return entityTypes;
    }

    /** Empty when not set. */
    public Map<String, Ontology> relationOntology() {
        return relationOntology;
    }

    public static final class Builder {
        private Method method = Method.REGEX;
        private LlmClient llm;
        private boolean dedupEnabled;
        private double dedupThreshold = 0.92;
        private int maxEntitiesPerChunk = 25;
        private boolean extractRelations;
        private boolean crossChunkRelations;
        private List<String> entityTypes;
        private Map<String, Ontology> relationOntology;

        public Builder method(Method m) {
            this.method = m;
            return this;
        }

        public Builder llm(LlmClient c) {
            this.llm = c;
            return this;
        }

        public Builder dedupEnabled(boolean v) {
            this.dedupEnabled = v;
            return this;
        }

        public Builder dedupThreshold(double v) {
            this.dedupThreshold = v;
            return this;
        }

        public Builder maxEntitiesPerChunk(int v) {
            this.maxEntitiesPerChunk = v;
            return this;
        }

        public Builder extractRelations(boolean v) {
            this.extractRelations = v;
            return this;
        }

        public Builder crossChunkRelations(boolean v) {
            this.crossChunkRelations = v;
            return this;
        }

        public Builder entityTypes(List<String> v) {
            this.entityTypes = v;
            return this;
        }

        public Builder relationOntology(Map<String, Ontology> v) {
            this.relationOntology = v;
            return this;
        }

        public ExtractionConfig build() {
            return new ExtractionConfig(this);
        }
    }
}
