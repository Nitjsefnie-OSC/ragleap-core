package com.ragleap.graph;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Merges near-duplicate entity names into one canonical form (port of ragleap_graph.extraction.EntityDeduplicator).
 * Pure string similarity, no embeddings. Each name is compared with the FIRST member of every existing cluster; the
 * canonical name of a cluster is its longest member (by code points, the first one wins a tie).
 */
public final class EntityDeduplicator {
    private final double threshold;

    public EntityDeduplicator() {
        this(0.92);
    }

    public EntityDeduplicator(double threshold) {
        if (!(threshold > 0.0 && threshold <= 1.0)) {
            throw new IllegalArgumentException("threshold must be in (0.0, 1.0]");
        }
        this.threshold = threshold;
    }

    /** Returns {original name: canonical name}, in cluster order. */
    public Map<String, String> resolve(List<String> names) {
        Map<String, String> mapping = new LinkedHashMap<>();
        if (names == null || names.isEmpty()) {
            return mapping;
        }
        List<List<String>> clusters = new ArrayList<>();
        for (String name : names) {
            String norm = normalize(name);
            boolean placed = false;
            for (List<String> cluster : clusters) {
                String clusterNorm = normalize(cluster.get(0));
                if (SequenceMatch.ratio(norm, clusterNorm) >= threshold) {
                    cluster.add(name);
                    placed = true;
                    break;
                }
            }
            if (!placed) {
                List<String> fresh = new ArrayList<>();
                fresh.add(name);
                clusters.add(fresh);
            }
        }
        for (List<String> cluster : clusters) {
            String canonical = cluster.get(0);
            int bestLen = canonical.codePointCount(0, canonical.length());
            for (String name : cluster) {
                int len = name.codePointCount(0, name.length());
                if (len > bestLen) {
                    canonical = name;
                    bestLen = len;
                }
            }
            for (String name : cluster) {
                mapping.put(name, canonical);
            }
        }
        return mapping;
    }

    /** Python: lowercase, remove . - _ , then collapse whitespace runs to one space and strip. */
    static String normalize(String name) {
        String lower = PyText.lower(name);
        StringBuilder sb = new StringBuilder();
        boolean pendingSpace = false;
        for (int i = 0; i < lower.length();) {
            int cp = lower.codePointAt(i);
            i += Character.charCount(cp);
            if (cp == '.' || cp == '-' || cp == '_' || cp == ',') {
                continue;
            }
            if (PyText.isSpace(cp)) {
                pendingSpace = true;
                continue;
            }
            if (pendingSpace && sb.length() > 0) {
                sb.append(' ');
            }
            pendingSpace = false;
            sb.appendCodePoint(cp);
        }
        return sb.toString();
    }
}
