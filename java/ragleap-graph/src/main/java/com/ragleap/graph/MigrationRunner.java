package com.ragleap.graph;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.LongSupplier;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Discovers and applies pending migrations in order (port of ragleap_graph.migrations.runner.MigrationRunner).
 * Not safe to run concurrently with application writes: run it in a maintenance window, after taking a dump.
 */
public final class MigrationRunner {
    private static final Logger LOG = Logger.getLogger(MigrationRunner.class.getName());

    private static final String CREATE_RECORD = "CREATE (m:_Migration {\n"
            + "    id: $id,\n"
            + "    description: $description,\n"
            + "    applied_at: datetime(),\n"
            + "    execution_time_ms: $elapsed_ms,\n"
            + "    result: $result_json\n"
            + "})";
    private static final String STATUS_QUERY = "MATCH (m:_Migration {id: $id}) "
            + "RETURN m.applied_at AS applied_at, "
            + "       m.execution_time_ms AS elapsed_ms";

    private final CypherRunner session;
    private final List<Migration> migrations;
    private final LongSupplier nanoClock;

    public MigrationRunner(CypherRunner runner, List<Migration> migrations) {
        this(runner, migrations, System::nanoTime);
    }

    MigrationRunner(CypherRunner runner, List<Migration> migrations, LongSupplier nanoClock) {
        if (runner == null) {
            throw new IllegalStateException("MigrationRunner requires an active Neo4j driver. "
                    + "Cannot run migrations without a database connection.");
        }
        this.session = runner;
        List<Migration> sorted = new ArrayList<>(migrations);
        sorted.sort((a, b) -> CodePoints.compare(a.id(), b.id()));
        this.migrations = Collections.unmodifiableList(sorted);
        this.nanoClock = nanoClock;
    }

    /** Runner over the index's connection; fails like Python's "driver is None" when the server is unreachable. */
    public static MigrationRunner forIndex(GraphIndex index, List<Migration> migrations) {
        return new MigrationRunner(index.runnerOrNull(), migrations);
    }

    public List<Migration> migrations() {
        return migrations;
    }

    public List<Map<String, Object>> runPending() {
        return runPending(false);
    }

    /**
     * Applies all pending migrations in order. With dryRun, only reports what would run. Stops at the first failure
     * (IllegalStateException; no :_Migration record is written for the failed step and later steps do not run).
     */
    public List<Map<String, Object>> runPending(boolean dryRun) {
        if (!dryRun) {
            LOG.warning("About to apply pending schema migrations. Ensure you have a database dump before "
                    + "proceeding - see docs/operations/backup-and-restore.md. Migrations are NOT safe to run "
                    + "concurrently with application writes; run during a maintenance window.");
        }
        List<Map<String, Object>> results = new ArrayList<>();
        for (Migration migration : migrations) {
            if (migration.isApplied(session)) {
                LOG.fine("Migration " + migration.id() + " already applied, skipping");
                continue;
            }
            if (dryRun) {
                LOG.info("[DRY RUN] Would apply: " + migration.id() + " - " + migration.description());
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("id", migration.id());
                entry.put("description", migration.description());
                entry.put("status", "pending");
                results.add(entry);
                continue;
            }
            LOG.info("Applying migration: " + migration.id() + " - " + migration.description());
            long startMs = Math.floorDiv(nanoClock.getAsLong(), 1_000_000L);
            Map<String, Object> result;
            try {
                result = migration.up(session);
            } catch (RuntimeException e) {
                String msg = e.getMessage() == null ? "" : e.getMessage();
                LOG.log(Level.SEVERE, "Migration " + migration.id() + " FAILED: " + msg, e);
                throw new IllegalStateException("Migration " + migration.id() + " failed: " + msg + ". "
                        + "The runner has stopped. No subsequent "
                        + "migrations have been applied. If the graph is "
                        + "in a partial state, restore from a "
                        + "pre-migration dump - see "
                        + "docs/operations/backup-and-restore.md", e);
            }
            long elapsedMs = Math.floorDiv(nanoClock.getAsLong(), 1_000_000L) - startMs;

            Map<String, Object> params = new LinkedHashMap<>();
            params.put("id", migration.id());
            params.put("description", migration.description());
            params.put("elapsed_ms", elapsedMs);
            params.put("result_json", PyJson.dumps(result));
            session.run(CREATE_RECORD, params);

            LOG.info("Migration " + migration.id() + " applied successfully in " + elapsedMs + "ms: " + result);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", migration.id());
            entry.put("description", migration.description());
            entry.put("status", "applied");
            entry.put("elapsed_ms", elapsedMs);
            entry.put("result", result);
            results.add(entry);
        }
        return results;
    }

    /**
     * Status of all known migrations. applied_at is the string the server returns (the Python driver's str() of a
     * datetime looks different); a null value becomes "None" as in Python.
     */
    public List<Map<String, Object>> status() {
        List<Map<String, Object>> statuses = new ArrayList<>();
        for (Migration migration : migrations) {
            boolean applied = migration.isApplied(session);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", migration.id());
            entry.put("description", migration.description());
            entry.put("applied", applied);
            if (applied) {
                List<Map<String, Object>> rows = session.run(STATUS_QUERY, Map.of("id", migration.id()));
                Map<String, Object> record = rows.isEmpty() ? null : rows.get(0);
                if (record != null && !record.isEmpty()) {
                    Object at = record.get("applied_at");
                    entry.put("applied_at", at == null ? "None" : String.valueOf(at));
                    entry.put("elapsed_ms", record.get("elapsed_ms"));
                }
            }
            statuses.add(entry);
        }
        return statuses;
    }
}
