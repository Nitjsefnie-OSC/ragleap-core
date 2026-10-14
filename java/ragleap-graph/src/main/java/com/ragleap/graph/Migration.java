package com.ragleap.graph;

import java.util.List;
import java.util.Map;

/** One schema migration step (port of ragleap_graph.migrations.base.Migration). */
public abstract class Migration {
    /** Unique, sortable id, conventionally NNNN_short_description. Migrations run in code-point order of their id. */
    public abstract String id();

    public abstract String description();

    /** Applies the migration; any RuntimeException is treated as a hard failure by the runner. */
    public abstract Map<String, Object> up(CypherRunner session);

    /** Most graph migrations are not reversible; the default says so (Python: NotImplementedError). */
    public Map<String, Object> down(CypherRunner session) {
        throw new UnsupportedOperationException("Migration " + id() + " does not support down(). "
                + "Restore from a database dump instead - see "
                + "docs/operations/backup-and-restore.md");
    }

    /** Default check: a :_Migration node with this id exists. */
    public boolean isApplied(CypherRunner session) {
        List<Map<String, Object>> rows = session.run(
                "MATCH (m:_Migration {id: $id}) RETURN count(m) > 0 AS applied", Map.of("id", id()));
        if (rows.isEmpty()) {
            throw new IllegalStateException("is_applied query returned no row");
        }
        return Boolean.TRUE.equals(rows.get(0).get("applied"));
    }
}
