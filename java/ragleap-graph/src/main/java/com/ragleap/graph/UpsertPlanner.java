package com.ragleap.graph;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Pure planning step of upsertDocument: extracts entities per chunk (regex, or an LLM through the configured
 * extractors), counts entities, entity pairs and typed relations, optionally merges near-duplicate entity names, and
 * picks the top ones, exactly as the Python implementation does. A failing extractor throws before anything is written.
 */
final class UpsertPlanner {
    private UpsertPlanner() {
    }

    record PairKey(String a, String b) {
    }

    record RelKey(String subject, String relationType, String object) {
    }

    record RelationEntry(String subject, String relationType, String object, int count) {
    }

    record Plan(List<Map.Entry<String, Integer>> topEntities, Map<String, String> entityTypes,
                List<Map.Entry<PairKey, Integer>> topPairs, List<RelationEntry> topRelations) {
    }

    /** The extraction strategy of an index: the config plus the extractors built from it (Python builds them eagerly). */
    record Extraction(ExtractionConfig config, LlmEntityExtractor entities, LlmRelationExtractor relations) {
        static final Extraction REGEX = new Extraction(ExtractionConfig.regex(), null, null);

        static Extraction of(ExtractionConfig config) {
            LlmEntityExtractor entities = config.method() == ExtractionConfig.Method.LLM
                    ? new LlmEntityExtractor(config) : null;
            LlmRelationExtractor relations = config.extractRelations() ? new LlmRelationExtractor(config) : null;
            return new Extraction(config, entities, relations);
        }
    }

    private record Counters(Map<String, Integer> entities, Map<PairKey, Integer> pairs, Map<RelKey, Integer> relations) {
    }

    static Plan plan(List<Map<String, Object>> chunks, int maxEntities, int maxPairs, List<String> domainTerms) {
        return plan(chunks, maxEntities, maxPairs, domainTerms, Extraction.REGEX);
    }

    static Plan plan(List<Map<String, Object>> chunks, int maxEntities, int maxPairs, List<String> domainTerms,
            Extraction ex) {
        Map<String, Integer> entityCounter = new LinkedHashMap<>();
        Map<PairKey, Integer> pairCounter = new LinkedHashMap<>();
        Map<RelKey, Integer> relationCounter = new LinkedHashMap<>();
        Map<String, String> entityTypes = new HashMap<>();
        if (chunks != null) {
            for (Map<String, Object> chunk : chunks) {
                String text = chunkText(chunk);
                if (text.isEmpty()) {
                    continue;
                }
                List<Map.Entry<String, String>> found = collect(text, 12, domainTerms, ex);
                if (found.isEmpty()) {
                    continue;
                }
                List<String> unique = new ArrayList<>();
                Set<String> seen = new HashSet<>();
                for (Map.Entry<String, String> e : found) {
                    String ent = e.getKey();
                    String key = PyText.lower(ent);
                    if (!seen.add(key)) {
                        continue;
                    }
                    unique.add(ent);
                    entityCounter.merge(ent, 1, Integer::sum);
                    entityTypes.putIfAbsent(key, e.getValue());
                }
                for (int i = 0; i < unique.size(); i++) {
                    for (int j = i + 1; j < unique.size(); j++) {
                        String a = unique.get(i);
                        String b = unique.get(j);
                        if (a.equals(b)) {
                            continue;
                        }
                        pairCounter.merge(orderByLower(a, b), 1, Integer::sum);
                    }
                }
                if (ex.relations() != null) {
                    for (ExtractedRelation rel : ex.relations().extract(text, unique, domainTerms, false, entityTypes)) {
                        relationCounter.merge(new RelKey(rel.subject(), rel.relationType(), rel.object()), 1,
                                Integer::sum);
                    }
                }
            }
        }
        if (ex.relations() != null && ex.config().crossChunkRelations()) {
            List<String> all = new ArrayList<>(entityCounter.keySet());
            List<String> texts = new ArrayList<>();
            if (chunks != null) {
                for (Map<String, Object> chunk : chunks) {
                    String t = chunkText(chunk);
                    if (!t.isEmpty()) {
                        texts.add(t);
                    }
                }
            }
            String full = String.join("\n\n", texts);
            if (!full.isEmpty() && all.size() >= 2) {
                for (ExtractedRelation rel : ex.relations().extract(full, all, domainTerms, true, entityTypes)) {
                    relationCounter.merge(new RelKey(rel.subject(), rel.relationType(), rel.object()), 1,
                            Integer::sum);
                }
            }
        }
        if (ex.config().dedupEnabled() && !entityCounter.isEmpty()) {
            Counters merged = dedup(entityCounter, pairCounter, relationCounter, ex.config().dedupThreshold());
            entityCounter = merged.entities();
            pairCounter = merged.pairs();
            relationCounter = merged.relations();
        }
        List<RelationEntry> topRelations = new ArrayList<>();
        for (Map.Entry<RelKey, Integer> e : mostCommon(relationCounter, maxPairs)) {
            topRelations.add(new RelationEntry(e.getKey().subject(), e.getKey().relationType(), e.getKey().object(),
                    e.getValue()));
        }
        return new Plan(mostCommon(entityCounter, maxEntities), entityTypes, mostCommon(pairCounter, maxPairs),
                topRelations);
    }

    private static String chunkText(Map<String, Object> chunk) {
        Object raw = chunk.get("text");
        return raw == null ? "" : PyText.strip(raw.toString());
    }

    /** Python _collect_entities_for_chunk: (name, type) pairs, from the LLM or from the regex heuristic. */
    private static List<Map.Entry<String, String>> collect(String text, int max, List<String> domainTerms,
            Extraction ex) {
        List<Map.Entry<String, String>> out = new ArrayList<>();
        if (ex.config().method() == ExtractionConfig.Method.LLM) {
            for (ExtractedEntity e : ex.entities().extract(text, domainTerms)) {
                out.add(Map.entry(e.name(), e.type()));
            }
            return new ArrayList<>(out.subList(0, Math.min(max, out.size())));
        }
        for (String name : EntityExtraction.extractEntityCandidates(text, max, domainTerms)) {
            out.add(Map.entry(name, "UNKNOWN"));
        }
        return out;
    }

    /** Python _apply_entity_dedup: merge counters through the canonical-name mapping (exact-case lookups). */
    private static Counters dedup(Map<String, Integer> entityCounter, Map<PairKey, Integer> pairCounter,
            Map<RelKey, Integer> relationCounter, double threshold) {
        Map<String, String> mapping = new EntityDeduplicator(threshold).resolve(new ArrayList<>(entityCounter.keySet()));
        Map<String, Integer> entities = new LinkedHashMap<>();
        for (Map.Entry<String, Integer> e : entityCounter.entrySet()) {
            entities.merge(mapping.getOrDefault(e.getKey(), e.getKey()), e.getValue(), Integer::sum);
        }
        Map<PairKey, Integer> pairs = new LinkedHashMap<>();
        for (Map.Entry<PairKey, Integer> e : pairCounter.entrySet()) {
            String ca = mapping.getOrDefault(e.getKey().a(), e.getKey().a());
            String cb = mapping.getOrDefault(e.getKey().b(), e.getKey().b());
            if (ca.equals(cb)) {
                continue;
            }
            pairs.merge(orderByLower(ca, cb), e.getValue(), Integer::sum);
        }
        Map<RelKey, Integer> relations = new LinkedHashMap<>();
        for (Map.Entry<RelKey, Integer> e : relationCounter.entrySet()) {
            String cs = mapping.getOrDefault(e.getKey().subject(), e.getKey().subject());
            String co = mapping.getOrDefault(e.getKey().object(), e.getKey().object());
            if (cs.equals(co)) {
                continue;
            }
            relations.merge(new RelKey(cs, e.getKey().relationType(), co), e.getValue(), Integer::sum);
        }
        return new Counters(entities, pairs, relations);
    }

    /** Python: tuple(sorted((a, b), key=lambda s: s.lower())). */
    static PairKey orderByLower(String a, String b) {
        return PyText.compareCodePoints(PyText.lower(a), PyText.lower(b)) <= 0 ? new PairKey(a, b) : new PairKey(b, a);
    }

    /** Python Counter.most_common(n): highest counts first, first-seen order kept on ties. */
    static <K> List<Map.Entry<K, Integer>> mostCommon(Map<K, Integer> counter, int n) {
        List<Map.Entry<K, Integer>> items = new ArrayList<>();
        for (Map.Entry<K, Integer> e : counter.entrySet()) {
            items.add(Map.entry(e.getKey(), e.getValue()));
        }
        items.sort((x, y) -> Integer.compare(y.getValue(), x.getValue()));
        return new ArrayList<>(items.subList(0, Math.min(Math.max(n, 0), items.size())));
    }
}
