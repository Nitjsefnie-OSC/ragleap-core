package com.ragleap.graph;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** The registered migrations (port of ragleap_graph.migrations.registry). */
public final class Migrations {
    private Migrations() {
    }

    /** Backfill user_id = "" onto pre-0.6.5 nodes missing the property. */
    public static final class BackfillUserIdDefaults extends Migration {
        @Override
        public String id() {
            return "0001_backfill_user_id";
        }

        @Override
        public String description() {
            return "Backfill user_id='' onto Entity/Document/PairWeight/"
                    + "RelationWeight nodes written before v0.6.5 user_id= "
                    + "support. Without this, legacy nodes are invisible to "
                    + "find_* queries and silently duplicated on re-upsert.";
        }

        @Override
        public Map<String, Object> up(CypherRunner session) {
            return new LinkedHashMap<String, Object>(GraphBackfills.userIdDefaults(session, null));
        }
    }

    /** Backfill composite_key onto pre-0.6.7 nodes for concurrency safety. */
    public static final class BackfillCompositeKey extends Migration {
        @Override
        public String id() {
            return "0002_backfill_composite_key";
        }

        @Override
        public String description() {
            return "Backfill composite_key (SHA256 hash of identity fields) "
                    + "onto nodes written before v0.6.7. Required for the "
                    + "single-property uniqueness constraints that close "
                    + "the concurrent-duplicate race (issue #183).";
        }

        @Override
        public Map<String, Object> up(CypherRunner session) {
            return new LinkedHashMap<String, Object>(
                    GraphBackfills.compositeKey(session, null, GraphBackfills.DEFAULT_BATCH_SIZE));
        }
    }

    /** All known migrations, in the order they should be applied (Python: ALL_MIGRATIONS). */
    public static List<Migration> all() {
        return List.of(new BackfillUserIdDefaults(), new BackfillCompositeKey());
    }
}
