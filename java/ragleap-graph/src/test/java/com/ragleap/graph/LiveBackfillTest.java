package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Runs against a real Neo4j test server. Every test uses its own unique namespace or id suffix and removes its data. */
@EnabledIfEnvironmentVariable(named = "NEO4J_HTTP_URL", matches = ".+")
class LiveBackfillTest {
    private static final String LEGACY = "CREATE (:Document {id: 'legacy-doc-1', namespace: $ns}), "
            + "(:Entity {name: 'acme corp', namespace: $ns}), (:Entity {name: 'globex', namespace: $ns}), "
            + "(:PairWeight {document_id: 'legacy-doc-1', entity_a: 'acme corp', entity_b: 'globex', "
            + "namespace: $ns, weight: 1.0}), "
            + "(:RelationWeight {document_id: 'legacy-doc-1', subject: 'acme corp', relation_type: 'PARTNERED_WITH', "
            + "object: 'globex', namespace: $ns, weight: 1.0})";
    private static final String CO_OCCURS = "MATCH (a:Entity {name: 'globex', namespace: $ns}), "
            + "(b:Entity {name: 'acme corp', namespace: $ns}) "
            + "CREATE (a)-[:CO_OCCURS_WITH {namespace: $ns, weight: 1.0}]->(b)";

    private static GraphConfig config() {
        return new GraphConfig(System.getenv("NEO4J_HTTP_URL"),
                System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
    }

    private static long count(CypherRunner r, String cypher, Map<String, Object> params) {
        return ((Number) r.run(cypher, params).get(0).get("cnt")).longValue();
    }

    private static long nsCount(CypherRunner r, String ns) {
        return count(r, "MATCH (n) WHERE n.namespace = $ns RETURN count(n) AS cnt", Map.of("ns", ns));
    }

    private static List<Object> values(CypherRunner r, String cypher, Map<String, Object> params) {
        List<Object> out = new ArrayList<>();
        for (Map<String, Object> row : r.run(cypher, params)) {
            out.add(row.get("v"));
        }
        return out;
    }

    private static void cleanup(CypherRunner r, String ns) {
        r.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
    }

    private static Set<Object> keys(CypherRunner r, String label, String ns) {
        return new HashSet<>(values(r, "MATCH (n:" + label + " {namespace: $ns}) RETURN n.composite_key AS v",
                Map.of("ns", ns)));
    }

    @Test
    void backfillsFixLegacyData() {
        String ns = "ragleap_graph_java_backfill_" + UUID.randomUUID();
        String other = ns + "_other";
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                assertTrue(graph.healthCheck());
                direct.run(LEGACY, Map.of("ns", ns));
                direct.run(CO_OCCURS, Map.of("ns", ns));
                direct.run("CREATE (:Entity {name: 'untouched', namespace: $ns})", Map.of("ns", other));

                // user_id defaults
                assertEquals(Map.of("Entity", 2L, "Document", 1L, "PairWeight", 1L, "RelationWeight", 1L),
                        graph.backfillUserIdDefaults(ns));
                assertEquals(0L, count(direct, "MATCH (n) WHERE n.namespace = $ns AND n.user_id IS NULL "
                        + "AND (n:Entity OR n:Document OR n:PairWeight OR n:RelationWeight) RETURN count(n) AS cnt",
                        Map.of("ns", ns)));
                assertEquals(Map.of("Entity", 0L, "Document", 0L, "PairWeight", 0L, "RelationWeight", 0L),
                        graph.backfillUserIdDefaults(ns));
                assertEquals(1L, count(direct, "MATCH (n:Entity {namespace: $ns}) WHERE n.user_id IS NULL "
                        + "RETURN count(n) AS cnt", Map.of("ns", other)), "another namespace must stay untouched");

                // composite keys (batch size smaller than the Entity count, so batching is exercised)
                assertEquals(Map.of("Document", 1L, "Entity", 2L, "PairWeight", 1L, "RelationWeight", 1L),
                        graph.backfillCompositeKey(ns, 1));
                assertEquals(Set.of(CompositeKey.of(ns, "", "legacy-doc-1")), keys(direct, "Document", ns));
                assertEquals(Set.of(CompositeKey.of(ns, "", "acme corp"), CompositeKey.of(ns, "", "globex")),
                        keys(direct, "Entity", ns));
                assertEquals(Set.of(CompositeKey.of(ns, "", "legacy-doc-1", "acme corp", "globex")),
                        keys(direct, "PairWeight", ns));
                assertEquals(Set.of(CompositeKey.of(ns, "", "legacy-doc-1", "acme corp", "PARTNERED_WITH", "globex")),
                        keys(direct, "RelationWeight", ns));
                assertEquals(Map.of("Document", 0L, "Entity", 0L, "PairWeight", 0L, "RelationWeight", 0L),
                        graph.backfillCompositeKey(ns));

                // CO_OCCURS_WITH: stored as globex -> acme corp, key uses the sorted pair
                assertEquals(1L, graph.backfillCoOccursWithCompositeKey(ns, 1));
                assertEquals(List.of(CompositeKey.of(ns, "", "acme corp", "globex")),
                        values(direct, "MATCH ()-[r:CO_OCCURS_WITH]->() WHERE r.namespace = $ns "
                                + "RETURN r.composite_key AS v", Map.of("ns", ns)));
                assertEquals(0L, graph.backfillCoOccursWithCompositeKey(ns));
            } finally {
                cleanup(direct, ns);
                cleanup(direct, other);
            }
            assertEquals(0L, nsCount(direct, ns));
            assertEquals(0L, nsCount(direct, other));
        }
    }

    static final class LiveMarker extends Migration {
        private final String id;
        private final String suffix;

        LiveMarker(String id, String suffix) {
            this.id = id;
            this.suffix = suffix;
        }

        @Override
        public String id() {
            return id;
        }

        @Override
        public String description() {
            return "live-test copy of " + id;
        }

        @Override
        public Map<String, Object> up(CypherRunner session) {
            session.run("MERGE (t:_MigrationLiveTestMarker {suffix: $suffix}) SET t.touched_at = datetime()",
                    Map.of("suffix", suffix));
            return Map.<String, Object>of("marked", true);
        }
    }

    @Test
    void runnerAppliesRecordsAndIsIdempotent() {
        String suffix = "livetest_" + UUID.randomUUID().toString().substring(0, 8);
        try (QueryApiRunner direct = new QueryApiRunner(config())) {
            try {
                List<Migration> migs = List.of(new LiveMarker("0001_" + suffix, suffix),
                        new LiveMarker("0002_" + suffix, suffix));
                MigrationRunner runner = new MigrationRunner(direct, migs);

                List<Map<String, Object>> pending = runner.runPending(true);
                assertEquals(2, pending.size());
                assertTrue(pending.stream().allMatch(p -> "pending".equals(p.get("status"))));

                List<Map<String, Object>> applied = runner.runPending();
                assertEquals(2, applied.size());
                assertTrue(applied.stream().allMatch(a -> "applied".equals(a.get("status"))));
                assertTrue(applied.stream().allMatch(a -> Map.of("marked", true).equals(a.get("result"))));
                List<Object> stored = values(direct, "MATCH (m:_Migration) WHERE m.id ENDS WITH $suffix "
                        + "RETURN m.result AS v", Map.of("suffix", suffix));
                assertEquals(List.of("{\"marked\": true}", "{\"marked\": true}"), stored);

                assertTrue(runner.runPending().isEmpty(), "second run must be a no-op");
                for (Map<String, Object> st : runner.status()) {
                    assertEquals(true, st.get("applied"));
                    assertNotNull(st.get("applied_at"));
                    assertNotEquals("None", st.get("applied_at"));
                    assertTrue(((Number) st.get("elapsed_ms")).longValue() >= 0);
                }

                // the real registry: read-only dry run (nothing is applied on the shared test server)
                assertTrue(new MigrationRunner(direct, Migrations.all()).runPending(true).size() <= 2);
            } finally {
                direct.run("MATCH (m:_Migration) WHERE m.id ENDS WITH $suffix DETACH DELETE m", Map.of("suffix", suffix));
                direct.run("MATCH (t:_MigrationLiveTestMarker {suffix: $suffix}) DETACH DELETE t", Map.of("suffix", suffix));
            }
            assertEquals(0L, count(direct, "MATCH (m:_Migration) WHERE m.id ENDS WITH $suffix RETURN count(m) AS cnt",
                    Map.of("suffix", suffix)));
            assertEquals(0L, count(direct, "MATCH (t:_MigrationLiveTestMarker {suffix: $suffix}) RETURN count(t) AS cnt",
                    Map.of("suffix", suffix)));
        }
    }
}
