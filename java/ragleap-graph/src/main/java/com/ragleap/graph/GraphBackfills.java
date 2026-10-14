package com.ragleap.graph;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Session-level backfill logic shared by the GraphIndex methods and the migrations. Ported from
 * _backfill_user_id_defaults_session, _backfill_composite_key_session and
 * GraphIndex.backfill_co_occurs_with_composite_key (ragleap-graph 0.9.0). A null runner means "not available":
 * every count is zero, like Python's "if not self.driver".
 */
final class GraphBackfills {
    static final int DEFAULT_BATCH_SIZE = 500;

    private static final List<String> USER_ID_LABELS = List.of("Entity", "Document", "PairWeight", "RelationWeight");
    private static final List<String> COMPOSITE_LABELS = List.of("Document", "Entity", "PairWeight", "RelationWeight");

    private static final String UPDATE_NODES = "UNWIND $batch AS row\n"
            + "MATCH (n) WHERE elementId(n) = row.eid\n"
            + "SET n.composite_key = row.composite_key";
    private static final String UPDATE_RELATIONSHIPS = "UNWIND $batch AS row\n"
            + "MATCH ()-[r:CO_OCCURS_WITH]-() WHERE elementId(r) = row.eid\n"
            + "SET r.composite_key = row.composite_key";

    private GraphBackfills() {
    }

    private static Map<String, Long> zeroCounts(List<String> labels) {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String label : labels) {
            counts.put(label, 0L);
        }
        return counts;
    }

    private static Map<String, Object> namespaceParams(String namespace) {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("namespace", namespace == null ? "" : namespace);
        return params;
    }

    static Map<String, Long> userIdDefaults(CypherRunner session, String namespace) {
        Map<String, Long> counts = zeroCounts(USER_ID_LABELS);
        if (session == null) {
            return counts;
        }
        String nsFilter = namespace != null ? "AND n.namespace = $namespace" : "";
        for (String label : USER_ID_LABELS) {
            List<Map<String, Object>> rows = session.run(
                    "MATCH (n:" + label + ")\n"
                            + "WHERE n.user_id IS NULL " + nsFilter + "\n"
                            + "SET n.user_id = \"\"\n"
                            + "RETURN count(n) AS updated",
                    namespaceParams(namespace));
            counts.put(label, rows.isEmpty() ? 0L : ((Number) rows.get(0).get("updated")).longValue());
        }
        return counts;
    }

    static Map<String, Long> compositeKey(CypherRunner session, String namespace, int batchSize) {
        Map<String, Long> counts = zeroCounts(COMPOSITE_LABELS);
        if (session == null) {
            return counts;
        }
        String nsFilter = namespace != null ? "AND n.namespace = $namespace" : "";
        for (String label : COMPOSITE_LABELS) {
            List<Map<String, Object>> records = new ArrayList<>(
                    session.run(readQuery(label, nsFilter), namespaceParams(namespace)));
            List<Map<String, Object>> updates = new ArrayList<>();
            for (Map<String, Object> r : records) {
                Map<String, Object> u = new LinkedHashMap<>();
                u.put("eid", r.get("eid"));
                u.put("composite_key", nodeKey(label, r));
                updates.add(u);
            }
            writeBatches(session, UPDATE_NODES, updates, batchSize);
            counts.put(label, (long) updates.size());
        }
        return counts;
    }

    static long coOccursCompositeKey(CypherRunner session, String namespace, int batchSize) {
        if (session == null) {
            return 0;
        }
        String nsFilter = namespace != null ? "AND r.namespace = $namespace" : "";
        String read = "MATCH ()-[r:CO_OCCURS_WITH]-() "
                + "WHERE r.composite_key IS NULL " + nsFilter + " "
                + "WITH DISTINCT r "
                + "RETURN elementId(r) AS eid, r.namespace AS namespace, "
                + "r.user_id AS user_id, startNode(r).name AS a, endNode(r).name AS b";
        List<Map<String, Object>> records = new ArrayList<>(session.run(read, namespaceParams(namespace)));
        List<Map<String, Object>> updates = new ArrayList<>();
        for (Map<String, Object> r : records) {
            String a = orEmpty(r.get("a"));
            String b = orEmpty(r.get("b"));
            if (CodePoints.compare(a, b) > 0) {
                String t = a;
                a = b;
                b = t;
            }
            Map<String, Object> u = new LinkedHashMap<>();
            u.put("eid", r.get("eid"));
            u.put("composite_key", CompositeKey.of(orEmpty(r.get("namespace")), orEmpty(r.get("user_id")), a, b));
            updates.add(u);
        }
        writeBatches(session, UPDATE_RELATIONSHIPS, updates, batchSize);
        return updates.size();
    }

    private static String readQuery(String label, String nsFilter) {
        String head = "MATCH (n:" + label + ") WHERE n.composite_key IS NULL " + nsFilter + " "
                + "RETURN elementId(n) AS eid, n.namespace AS namespace, n.user_id AS user_id, ";
        return switch (label) {
            case "Document" -> head + "n.id AS id";
            case "Entity" -> head + "n.name AS name";
            case "PairWeight" -> head + "n.document_id AS document_id, n.entity_a AS entity_a, n.entity_b AS entity_b";
            case "RelationWeight" -> head + "n.document_id AS document_id, n.subject AS subject, "
                    + "n.relation_type AS relation_type, n.object AS object";
            default -> throw new IllegalArgumentException(label);
        };
    }

    private static String nodeKey(String label, Map<String, Object> r) {
        String ns = orEmpty(r.get("namespace"));
        String uid = orEmpty(r.get("user_id"));
        return switch (label) {
            case "Document" -> CompositeKey.of(ns, uid, pyStr(r.get("id")));
            case "Entity" -> CompositeKey.of(ns, uid, pyStr(r.get("name")));
            case "PairWeight" -> CompositeKey.of(ns, uid, pyStr(r.get("document_id")),
                    orEmpty(r.get("entity_a")), orEmpty(r.get("entity_b")));
            case "RelationWeight" -> CompositeKey.of(ns, uid, pyStr(r.get("document_id")),
                    orEmpty(r.get("subject")), orEmpty(r.get("relation_type")), orEmpty(r.get("object")));
            default -> throw new IllegalArgumentException(label);
        };
    }

    /**
     * Python: for i in range(0, len(updates), batch_size). A zero step raises ValueError (even with no updates);
     * a negative step gives an empty range, so nothing is written while the count is still reported.
     */
    private static void writeBatches(CypherRunner session, String cypher, List<Map<String, Object>> updates,
            int batchSize) {
        if (batchSize == 0) {
            throw new IllegalArgumentException("range() arg 3 must not be zero");
        }
        if (batchSize < 0) {
            return;
        }
        for (int i = 0; i < updates.size(); i += batchSize) {
            List<Map<String, Object>> batch = new ArrayList<>(
                    updates.subList(i, Math.min(i + batchSize, updates.size())));
            Map<String, Object> params = new LinkedHashMap<>();
            params.put("batch", batch);
            session.run(cypher, params);
        }
    }

    private static boolean truthy(Object v) {
        if (v == null) {
            return false;
        }
        if (v instanceof Boolean b) {
            return b;
        }
        if (v instanceof Number n) {
            return n.doubleValue() != 0.0;
        }
        if (v instanceof CharSequence s) {
            return s.length() > 0;
        }
        if (v instanceof Collection<?> c) {
            return !c.isEmpty();
        }
        if (v instanceof Map<?, ?> m) {
            return !m.isEmpty();
        }
        return true;
    }

    /** Python: (value or ""), which must then be a str. */
    private static String orEmpty(Object v) {
        if (!truthy(v)) {
            return "";
        }
        if (v instanceof String s) {
            return s;
        }
        throw new IllegalArgumentException("sequence item: expected str instance, " + v.getClass().getSimpleName() + " found");
    }

    /** Python: str(value or ""). */
    private static String pyStr(Object v) {
        if (!truthy(v)) {
            return "";
        }
        if (v instanceof String s) {
            return s;
        }
        if (v instanceof Boolean b) {
            return b ? "True" : "False";
        }
        if (v instanceof Double || v instanceof Float) {
            return PyJson.floatRepr(((Number) v).doubleValue());
        }
        return String.valueOf(v);
    }
}
