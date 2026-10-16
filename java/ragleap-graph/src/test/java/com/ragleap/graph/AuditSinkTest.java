package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Offline tests of the audit pieces: strict JSON, libpq URL conversion, and the never-throw contract. */
class AuditSinkTest {
    @Test
    void auditJsonFormatsLikePythonJsonDumps() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 1);
        m.put("b", List.of(1, 2.5, true));
        m.put("c", null);
        assertEquals("{\"a\": 1, \"b\": [1, 2.5, true], \"c\": null}", AuditJson.dumps(m));
    }

    @Test
    void auditJsonRejectsWhatPythonRejects() {
        assertThrows(IllegalArgumentException.class, () -> AuditJson.dumps(Map.of("s", Set.of(1))));
        assertThrows(IllegalArgumentException.class, () -> AuditJson.dumps(Map.of("a", new int[] {1})));
        assertThrows(IllegalArgumentException.class, () -> AuditJson.dumps(Map.of("o", new Object())));
    }

    @Test
    void libpqUrlBasic() {
        LibpqUrl.Target t = LibpqUrl.parse("postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test");
        assertEquals("jdbc:postgresql://localhost:5433/ragleap_java_test", t.jdbcUrl());
        assertEquals("ragleap", t.user());
        assertEquals("ragleap", t.password());
    }

    @Test
    void libpqUrlDefaultsAndBothSchemes() {
        LibpqUrl.Target t = LibpqUrl.parse("postgres://u@db.example.com/mydb");
        assertEquals("jdbc:postgresql://db.example.com:5432/mydb", t.jdbcUrl());
        assertEquals("u", t.user());
        assertNull(t.password());
        assertEquals("jdbc:postgresql://localhost:5432/", LibpqUrl.parse("postgresql:///").jdbcUrl());
    }

    @Test
    void libpqUrlDecodesUserInfoAndKeepsTheQuery() {
        LibpqUrl.Target t = LibpqUrl.parse("postgresql://us%40er:p%40ss%3Aword%2B1@db.example.com/mydb?sslmode=require");
        assertEquals("us@er", t.user());
        assertEquals("p@ss:word+1", t.password());
        assertEquals("jdbc:postgresql://db.example.com:5432/mydb?sslmode=require", t.jdbcUrl());
    }

    @Test
    void libpqUrlHandlesIpv6AndUnderscoresInHostNames() {
        assertEquals("jdbc:postgresql://[::1]:6543/db", LibpqUrl.parse("postgresql://u:p@[::1]:6543/db").jdbcUrl());
        assertEquals("jdbc:postgresql://my_host:5432/db", LibpqUrl.parse("postgresql://u:p@my_host:5432/db").jdbcUrl());
    }

    @Test
    void libpqUrlRejectsWhatItCannotConvert() {
        assertThrows(IllegalArgumentException.class, () -> LibpqUrl.parse("mysql://u:p@h/db"));
        assertThrows(IllegalArgumentException.class, () -> LibpqUrl.parse("not a url"));
        assertThrows(IllegalArgumentException.class, () -> LibpqUrl.parse(null));
    }

    @Test
    void aDisabledSinkNeverOpensAConnection() {
        int[] opened = {0};
        PostgresAuditSink sink = new PostgresAuditSink(null, url -> {
            opened[0]++;
            throw new SQLException("must not be called");
        });
        assertFalse(sink.enabled());
        sink.log("u", "ns", "a", "d", 1, Map.of());
        assertEquals(0, opened[0]);
    }

    @Test
    void aFailingConnectionNeverBreaksLog() {
        PostgresAuditSink sink = new PostgresAuditSink("postgresql://x", url -> {
            throw new SQLException("down");
        });
        sink.log("u", "ns", "a", "d", 1, Map.of());
        sink.log("u", "ns", "a", "d", 1, null);
        sink.close();
    }

    @Test
    void closeWithoutAConnectionIsSafe() {
        PostgresAuditSink sink = new PostgresAuditSink("postgresql://x", url -> {
            throw new SQLException("down");
        });
        sink.close();
        sink.close();
    }
}
