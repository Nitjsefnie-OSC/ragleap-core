package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Runs against a real Postgres test database (RAGLEAP_JAVA_TEST_DATABASE_URL, a libpq URI) and, for the second test,
 * a real Neo4j test server. Every test uses its own unique audit user and removes its rows.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_JAVA_TEST_DATABASE_URL", matches = ".+")
class LiveAuditTest {
    private static String url() {
        return System.getenv("RAGLEAP_JAVA_TEST_DATABASE_URL");
    }

    private static Connection direct() throws SQLException {
        LibpqUrl.Target t = LibpqUrl.parse(url());
        return DriverManager.getConnection(t.jdbcUrl(), t.user(), t.password());
    }

    private static void deleteRows(String user) {
        try (Connection c = direct(); PreparedStatement ps = c.prepareStatement(
                "DELETE FROM ragleap_graph_audit_log WHERE user_id = ?")) {
            ps.setString(1, user);
            ps.executeUpdate();
        } catch (SQLException ignored) {
            // the table may not exist if nothing was written
        }
    }

    private static long count(String user) throws SQLException {
        try (Connection c = direct(); PreparedStatement ps = c.prepareStatement(
                "SELECT count(*) FROM ragleap_graph_audit_log WHERE user_id = ?")) {
            ps.setString(1, user);
            try (ResultSet rs = ps.executeQuery()) {
                rs.next();
                return rs.getLong(1);
            }
        }
    }

    @Test
    void theSinkWritesRealRows() throws Exception {
        String user = "audit-test-" + UUID.randomUUID();
        PostgresAuditSink sink = new PostgresAuditSink(url());
        try {
            sink.log(user, "ns1", "upsert_document", "doc-1", 3, Map.of("relationships_indexed", 2));
            sink.log(user, "", "find_x", null, null, null);
            try (Connection c = direct(); PreparedStatement ps = c.prepareStatement(
                    "SELECT namespace, action, document_id, entity_count, detail->>'relationships_indexed' AS rel, "
                            + "(detail IS NULL) AS no_detail FROM ragleap_graph_audit_log WHERE user_id = ? ORDER BY id")) {
                ps.setString(1, user);
                try (ResultSet rs = ps.executeQuery()) {
                    assertTrue(rs.next());
                    assertEquals("ns1", rs.getString("namespace"));
                    assertEquals("upsert_document", rs.getString("action"));
                    assertEquals("doc-1", rs.getString("document_id"));
                    assertEquals(3, rs.getInt("entity_count"));
                    assertEquals("2", rs.getString("rel"));
                    assertFalse(rs.getBoolean("no_detail"));
                    assertTrue(rs.next());
                    assertNull(rs.getString("namespace"), "an empty namespace is stored as NULL");
                    assertEquals("find_x", rs.getString("action"));
                    assertNull(rs.getString("document_id"));
                    rs.getInt("entity_count");
                    assertTrue(rs.wasNull());
                    assertTrue(rs.getBoolean("no_detail"));
                    assertFalse(rs.next());
                }
            }
        } finally {
            sink.close();
            deleteRows(user);
        }
        assertEquals(0L, count(user));
    }

    @Test
    void aGraphIndexWritesAnAuditRowOnUpsert() throws Exception {
        String neo4j = System.getenv("NEO4J_HTTP_URL");
        Assumptions.assumeTrue(neo4j != null && !neo4j.isEmpty(), "needs a Neo4j test server");
        String user = "audit-test-" + UUID.randomUUID();
        String ns = "ragleap_graph_java_audit_" + UUID.randomUUID();
        GraphConfig cfg = new GraphConfig(neo4j, System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
        PostgresAuditSink sink = new PostgresAuditSink(url());
        try (QueryApiRunner direct = new QueryApiRunner(cfg);
                GraphIndex graph = new GraphIndex(cfg, ExtractionConfig.regex(), sink)) {
            try {
                UpsertSummary s = graph.upsertDocument("doc-1", "Audit Test",
                        List.of(Map.of("text", "Acme Corp announced a partnership with Globex Industries.")), ns, user,
                        80, 150, null);
                assertTrue(s.success(), String.valueOf(s));
                try (Connection c = direct(); PreparedStatement ps = c.prepareStatement(
                        "SELECT action, document_id, entity_count, namespace, detail->>'relationships_indexed' AS rel "
                                + "FROM ragleap_graph_audit_log WHERE user_id = ?")) {
                    ps.setString(1, user);
                    try (ResultSet rs = ps.executeQuery()) {
                        assertTrue(rs.next());
                        assertEquals("upsert_document", rs.getString("action"));
                        assertEquals("doc-1", rs.getString("document_id"));
                        assertEquals(s.entitiesIndexed(), rs.getInt("entity_count"));
                        assertEquals(ns, rs.getString("namespace"));
                        assertEquals(String.valueOf(s.relationshipsIndexed()), rs.getString("rel"));
                        assertFalse(rs.next(), "exactly one audit row per upsert");
                    }
                }
            } finally {
                direct.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
            }
        } finally {
            deleteRows(user);
        }
        assertEquals(0L, count(user));
    }
}
