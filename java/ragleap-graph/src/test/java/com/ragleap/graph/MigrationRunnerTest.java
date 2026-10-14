package com.ragleap.graph;

import static com.ragleap.graph.MigrationFakes.DEFAULT_STATUS_ROW;
import static com.ragleap.graph.MigrationFakes.row;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ragleap.graph.MigrationFakes.SessionFake;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;

/** Offline tests of the migration runner and the backfills (ports of the offline Python tests plus edge cases). */
class MigrationRunnerTest {
    static final class FakeMigration extends Migration {
        private final String id;
        private final String description;
        private final Supplier<Map<String, Object>> up;

        FakeMigration(String id, String description, Supplier<Map<String, Object>> up) {
            this.id = id;
            this.description = description;
            this.up = up;
        }

        @Override
        public String id() {
            return id;
        }

        @Override
        public String description() {
            return description;
        }

        @Override
        public Map<String, Object> up(CypherRunner session) {
            return up.get();
        }
    }

    private static FakeMigration fake(String id) {
        return new FakeMigration(id, "fake migration", () -> Map.<String, Object>of("updated", 1));
    }

    @Test
    void requiresARunner() {
        IllegalStateException e = assertThrows(IllegalStateException.class, () -> new MigrationRunner(null, List.of()));
        assertTrue(e.getMessage().contains("requires an active Neo4j driver"));
    }

    @Test
    void sortsMigrationsById() {
        MigrationRunner runner = new MigrationRunner(new SessionFake(), List.of(fake("0002_second"), fake("0001_first")));
        assertEquals(List.of("0001_first", "0002_second"), runner.migrations().stream().map(Migration::id).toList());
    }

    @Test
    void dryRunReportsWithoutExecuting() {
        AtomicBoolean called = new AtomicBoolean();
        Migration m = new FakeMigration("0001_test", "fake migration", () -> {
            called.set(true);
            return Map.<String, Object>of("updated", 99);
        });
        SessionFake fake = new SessionFake();
        List<Map<String, Object>> results = new MigrationRunner(fake, List.of(m)).runPending(true);
        assertFalse(called.get(), "dry run must not call up()");
        assertEquals(1, results.size());
        assertEquals("pending", results.get(0).get("status"));
        assertEquals("0001_test", results.get(0).get("id"));
        assertTrue(fake.created.isEmpty());
    }

    @Test
    void skipsAlreadyAppliedMigrations() {
        SessionFake fake = new SessionFake(List.of("0001_already_done"), Map.of(), DEFAULT_STATUS_ROW);
        List<Map<String, Object>> results = new MigrationRunner(fake, List.of(fake("0001_already_done"))).runPending();
        assertTrue(results.isEmpty());
        assertTrue(fake.created.isEmpty());
    }

    @Test
    void appliesPendingMigrationsAndRecordsThem() {
        SessionFake fake = new SessionFake();
        Migration m = new FakeMigration("0001_test", "does a thing", () -> Map.<String, Object>of("Entity", 5));
        List<Map<String, Object>> results = new MigrationRunner(fake, List.of(m)).runPending();
        assertEquals(1, results.size());
        assertEquals("applied", results.get(0).get("status"));
        assertEquals("0001_test", results.get(0).get("id"));
        assertEquals(Map.of("Entity", 5), results.get(0).get("result"));
        assertTrue(results.get(0).containsKey("elapsed_ms"));
        assertEquals(1, fake.created.size());
        assertEquals("0001_test", fake.created.get(0).get("id"));
        assertEquals("does a thing", fake.created.get(0).get("description"));
        assertEquals("{\"Entity\": 5}", fake.created.get(0).get("result_json"));
    }

    @Test
    void stopsOnFirstFailureAndDoesNotContinue() {
        List<String> ran = new ArrayList<>();
        Migration failing = new FakeMigration("0001_fails", "fake migration", () -> {
            throw new IllegalArgumentException("simulated migration failure");
        });
        Migration second = new FakeMigration("0002_never_reached", "fake migration", () -> {
            ran.add("second");
            return Map.<String, Object>of();
        });
        SessionFake fake = new SessionFake();
        MigrationRunner runner = new MigrationRunner(fake, List.of(failing, second));
        IllegalStateException e = assertThrows(IllegalStateException.class, runner::runPending);
        assertTrue(e.getMessage().contains("0001_fails"));
        assertTrue(e.getMessage().contains("simulated migration failure"));
        assertTrue(ran.isEmpty(), "must not run the next migration after a failure");
        assertTrue(fake.created.isEmpty(), "a failed migration must not be recorded");
    }

    @Test
    void statusReportsAppliedAndPending() {
        SessionFake fake = new SessionFake(List.of("0001_applied"), Map.of(), DEFAULT_STATUS_ROW);
        List<Map<String, Object>> statuses = new MigrationRunner(fake,
                List.of(fake("0001_applied"), fake("0002_pending"))).status();
        assertEquals(true, statuses.get(0).get("applied"));
        assertEquals("2026-01-01T00:00:00Z", statuses.get(0).get("applied_at"));
        assertEquals(false, statuses.get(1).get("applied"));
        assertFalse(statuses.get(1).containsKey("applied_at"));
    }

    @Test
    void defaultDownIsNotSupported() {
        UnsupportedOperationException e = assertThrows(UnsupportedOperationException.class,
                () -> fake("0001_test").down(null));
        assertTrue(e.getMessage().contains("does not support down"));
    }

    @Test
    void registryHasUniqueSortedIds() {
        List<String> ids = Migrations.all().stream().map(Migration::id).toList();
        assertEquals(List.of("0001_backfill_user_id", "0002_backfill_composite_key"), ids);
    }

    @Test
    void batchSizeZeroIsRejectedAfterTheFirstRead() {
        SessionFake fake = new SessionFake();
        assertThrows(IllegalArgumentException.class, () -> GraphBackfills.compositeKey(fake, null, 0));
        assertEquals(1, fake.calls.size());
    }

    private static Map<String, Map<String, List<Map<String, Object>>>> entityRows(int n) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            list.add(row("eid", "4:e:" + i, "namespace", "n", "user_id", "u", "name", "e" + i));
        }
        return Map.of("composite", Map.of("Entity", list));
    }

    @Test
    void negativeBatchSizeWritesNothingButReportsTheCount() {
        SessionFake fake = new SessionFake(List.of(), entityRows(2), DEFAULT_STATUS_ROW);
        Map<String, Long> counts = GraphBackfills.compositeKey(fake, null, -1);
        assertEquals(2L, counts.get("Entity").longValue());
        assertTrue(fake.calls.stream().noneMatch(c -> c.cypher().contains("UNWIND")));
    }

    @Test
    void writesInBatches() {
        SessionFake fake = new SessionFake(List.of(), entityRows(7), DEFAULT_STATUS_ROW);
        GraphBackfills.compositeKey(fake, null, 3);
        assertEquals(3, fake.calls.stream().filter(c -> c.cypher().contains("UNWIND")).count());
    }

    @Test
    void userIdDefaultsReportsEveryLabel() {
        Map<String, Map<String, List<Map<String, Object>>>> rows = Map.of("user_id", Map.of(
                "Entity", List.of(row("updated", 3)), "RelationWeight", List.of(row("updated", 11))));
        Map<String, Long> counts = GraphBackfills.userIdDefaults(new SessionFake(List.of(), rows, DEFAULT_STATUS_ROW), null);
        assertEquals(Map.of("Entity", 3L, "Document", 0L, "PairWeight", 0L, "RelationWeight", 11L), counts);
        assertEquals(List.of("Entity", "Document", "PairWeight", "RelationWeight"), new ArrayList<>(counts.keySet()));
    }

    @Test
    void unreachableServerGivesZeroCountsAndNoRunner() {
        try (GraphIndex g = new GraphIndex(new GraphConfig("http://localhost:1", "u", "p"))) {
            assertFalse(g.isAvailable());
            assertEquals(Map.of("Entity", 0L, "Document", 0L, "PairWeight", 0L, "RelationWeight", 0L),
                    g.backfillUserIdDefaults());
            assertEquals(Map.of("Document", 0L, "Entity", 0L, "PairWeight", 0L, "RelationWeight", 0L),
                    g.backfillCompositeKey("ns", 10));
            assertEquals(0L, g.backfillCoOccursWithCompositeKey());
            assertThrows(IllegalStateException.class, () -> MigrationRunner.forIndex(g, Migrations.all()));
        }
    }
}
