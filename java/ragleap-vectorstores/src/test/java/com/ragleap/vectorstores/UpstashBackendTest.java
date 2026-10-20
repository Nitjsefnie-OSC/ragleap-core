package com.ragleap.vectorstores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** Unit tests that run everywhere (CI included); the Python comparison is in UpstashParityTest. */
class UpstashBackendTest {
    private static final String INFO = "{\"result\":{\"vectorCount\":0,\"pendingVectorCount\":0,\"indexSize\":0,"
            + "\"dimension\":8,\"similarityFunction\":\"COSINE\",\"denseIndex\":{\"dimension\":8,"
            + "\"similarityFunction\":\"COSINE\",\"embeddingModel\":\"x\"},\"sparseIndex\":null,\"namespaces\":{}}}";

    @Test
    void filterMatchesWhatPythonBuilt() {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("document_id", "it's");
        f.put("flag", true);
        f.put("n", 3);
        f.put("f", 1.5);
        f.put("g", 1e-07);
        f.put("none", null);
        f.put("sp", "x y");
        f.put("off", false);
        // string printed by the real Python UpstashBackend for the same input
        assertEquals("document_id = 'it''s' AND flag = true AND n = 3 AND f = 1.5 AND g = 1e-07 AND none = 'None' "
                + "AND sp = 'x y' AND off = false", UpstashBackend.buildFilter(f));
        assertEquals("", UpstashBackend.buildFilter(Map.of()));
        assertEquals("", UpstashBackend.buildFilter(null));
    }

    @Test
    void namespacePathEncodingKeepsSlashesAndValidEscapes() {
        // value printed by the real SDK path for the namespace "my ns/\u00e9"
        assertEquals("my%20ns/%C3%A9", UpstashBackend.encodePath("my ns/\u00e9"));
        assertEquals("a%20b%41%25zz", UpstashBackend.encodePath("a b%41%zz"));
        assertEquals("a+b,c:d@e!f$g&h'i(j)k*l;m=n~o_p-q.r", UpstashBackend.encodePath("a+b,c:d@e!f$g&h'i(j)k*l;m=n~o_p-q.r"));
    }

    @Test
    void naiveIsoFormatDropsZeroMicroseconds() {
        OffsetDateTime t = OffsetDateTime.of(2026, 10, 19, 10, 0, 0, 0, ZoneOffset.UTC);
        assertEquals("2026-10-19T10:00:00", UpstashBackend.pyIsoNaive(t));
        assertEquals("2026-10-19T10:00:00.123456", UpstashBackend.pyIsoNaive(t.withNano(123_456_000)));
    }

    @Test
    void urlAndTokenAreRequired(@TempDir Path tmp) {
        String reg = tmp.resolve("r.sqlite3").toString();
        assertThrows(IllegalArgumentException.class, () -> new UpstashBackend("", "t", "", reg));
        assertThrows(IllegalArgumentException.class, () -> new UpstashBackend("u", "", "", reg));
        assertThrows(IllegalArgumentException.class, () -> new UpstashBackend(null, "t", "", reg));
        assertThrows(IllegalArgumentException.class, () -> new UpstashBackend("u", null, "", reg));
    }

    @Test
    void initSchemaSendsBearerTokenAndChecksDimension(@TempDir Path tmp) throws Exception {
        AtomicReference<String> seen = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            seen.set(ex.getRequestMethod() + " " + ex.getRequestURI().getRawPath() + " "
                    + ex.getRequestHeaders().getFirst("Authorization"));
            byte[] data = INFO.getBytes(StandardCharsets.UTF_8);
            ex.sendResponseHeaders(200, data.length);
            ex.getResponseBody().write(data);
            ex.close();
        });
        server.start();
        try (UpstashBackend be = new UpstashBackend("http://127.0.0.1:" + server.getAddress().getPort(), "tok", "",
                tmp.resolve("r.sqlite3").toString())) {
            be.initSchema(8);
            assertEquals("POST /info Bearer tok", seen.get());
            IllegalStateException e = assertThrows(IllegalStateException.class, () -> be.initSchema(4));
            assertTrue(e.getMessage().contains("has dimension 8, but 4 was requested"), e.getMessage());
        } finally {
            server.stop(0);
        }
    }
}
