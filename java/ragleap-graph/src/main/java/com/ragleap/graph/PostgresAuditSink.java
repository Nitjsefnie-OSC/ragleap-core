package com.ragleap.graph;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Types;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.logging.Logger;

/**
 * Audit events in Postgres (port of ragleap_graph._audit.AuditLogger). Fully optional: pass an instance to
 * GraphIndex to enable audit logging. The PostgreSQL JDBC driver is NOT a dependency of this library: add
 * org.postgresql:postgresql to your own project (like Python's optional psycopg2 extra). Without it, a warning is
 * logged once and nothing is audited.
 *
 * <p>Like the Python class, it never throws from log(): a missing driver, an unreachable database or a failed write is
 * logged as a warning and swallowed, so the audited operation always succeeds. The table ragleap_graph_audit_log is
 * created on first use. databaseUrl is a libpq URI such as postgresql://user:password@host:5432/dbname; an empty or
 * null URL disables the sink.
 */
public final class PostgresAuditSink implements AuditSink {
    private static final Logger LOG = Logger.getLogger("ragleap_graph.audit");

    static final String CREATE_TABLE_SQL = "CREATE TABLE IF NOT EXISTS ragleap_graph_audit_log ("
            + "id BIGSERIAL PRIMARY KEY, "
            + "occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            + "user_id TEXT, namespace TEXT, action TEXT NOT NULL, document_id TEXT, entity_count INTEGER, "
            + "detail JSONB)";
    static final List<String> CREATE_INDEXES_SQL = List.of(
            "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_user_id ON ragleap_graph_audit_log (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_namespace ON ragleap_graph_audit_log (namespace)",
            "CREATE INDEX IF NOT EXISTS idx_ragleap_graph_audit_occurred_at ON ragleap_graph_audit_log (occurred_at)");
    static final String INSERT_SQL = "INSERT INTO ragleap_graph_audit_log "
            + "(user_id, namespace, action, document_id, entity_count, detail) VALUES (?, ?, ?, ?, ?, ?)";
    static final String NO_DRIVER_MESSAGE = "PostgreSQL JDBC driver not found on the classpath - audit logging is "
            + "disabled. Add org.postgresql:postgresql to your project to enable it.";

    /** Where connections come from; the default uses the PostgreSQL JDBC driver when it is on the classpath. */
    interface ConnectionFactory {
        Connection open(String databaseUrl) throws SQLException, DriverMissingException;
    }

    /** The PostgreSQL JDBC driver is not on the classpath. */
    static final class DriverMissingException extends Exception {
        private static final long serialVersionUID = 1L;
    }

    private final String databaseUrl;
    private final ConnectionFactory factory;
    private Connection conn;
    private boolean schemaReady;
    private boolean warnedNoDriver;

    public PostgresAuditSink(String databaseUrl) {
        this(databaseUrl, PostgresAuditSink::openWithDriver);
    }

    PostgresAuditSink(String databaseUrl, ConnectionFactory factory) {
        this.databaseUrl = databaseUrl;
        this.factory = factory;
    }

    /** True when a non-empty database URL was given. */
    public boolean enabled() {
        return databaseUrl != null && !databaseUrl.isEmpty();
    }

    private static Connection openWithDriver(String url) throws SQLException, DriverMissingException {
        try {
            Class.forName("org.postgresql.Driver");
        } catch (ClassNotFoundException e) {
            throw new DriverMissingException();
        }
        LibpqUrl.Target target = LibpqUrl.parse(url);
        Properties props = new Properties();
        if (target.user() != null) {
            props.setProperty("user", target.user());
        }
        if (target.password() != null) {
            props.setProperty("password", target.password());
        }
        return DriverManager.getConnection(target.jdbcUrl(), props);
    }

    private static boolean empty(String s) {
        return s == null || s.isEmpty();
    }

    private Connection connect() {
        if (conn != null) {
            return conn;
        }
        Connection c = null;
        try {
            c = factory.open(databaseUrl);
            c.setAutoCommit(true);
            conn = c;
            return c;
        } catch (DriverMissingException e) {
            if (!warnedNoDriver) {
                LOG.warning(NO_DRIVER_MESSAGE);
                warnedNoDriver = true;
            }
            return null;
        } catch (Exception e) {
            LOG.warning("Audit log connection failed, audit logging disabled for this call: " + e);
            closeQuietly(c);
            conn = null;
            return null;
        }
    }

    private boolean ensureSchema(Connection c) {
        if (schemaReady) {
            return true;
        }
        try (Statement st = c.createStatement()) {
            st.execute(CREATE_TABLE_SQL);
            for (String index : CREATE_INDEXES_SQL) {
                st.execute(index);
            }
            schemaReady = true;
            return true;
        } catch (Exception e) {
            LOG.warning("Audit log schema setup failed, audit logging disabled for this call: " + e);
            return false;
        }
    }

    private static void setText(PreparedStatement ps, int index, String value) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.VARCHAR);
        } else {
            ps.setString(index, value);
        }
    }

    /** Records one audit event. Never throws. */
    @Override
    public synchronized void log(String userId, String namespace, String action, String documentId,
            Integer entityCount, Map<String, Object> detail) {
        if (!enabled()) {
            return;
        }
        Connection c = connect();
        if (c == null) {
            return;
        }
        if (!ensureSchema(c)) {
            return;
        }
        try {
            String json = detail != null ? AuditJson.dumps(detail) : null;
            try (PreparedStatement ps = c.prepareStatement(INSERT_SQL)) {
                setText(ps, 1, empty(userId) ? null : userId);
                setText(ps, 2, empty(namespace) ? null : namespace);
                setText(ps, 3, action);
                setText(ps, 4, documentId);
                if (entityCount == null) {
                    ps.setNull(5, Types.INTEGER);
                } else {
                    ps.setInt(5, entityCount);
                }
                if (json == null) {
                    ps.setNull(6, Types.OTHER);
                } else {
                    ps.setObject(6, json, Types.OTHER);
                }
                ps.execute();
            }
        } catch (Exception e) {
            LOG.warning("Audit log write failed, continuing without it: " + e);
            dropConnection();
        }
    }

    private void dropConnection() {
        Connection c = conn;
        conn = null;
        closeQuietly(c);
    }

    private static void closeQuietly(Connection c) {
        if (c != null) {
            try {
                c.close();
            } catch (Exception ignored) {
                // closing is best effort
            }
        }
    }

    @Override
    public synchronized void close() {
        Connection c = conn;
        conn = null;
        closeQuietly(c);
    }
}
