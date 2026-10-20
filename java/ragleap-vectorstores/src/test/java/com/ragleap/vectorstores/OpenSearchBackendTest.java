package com.ragleap.vectorstores;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigInteger;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

/** Small unit tests that run everywhere (CI included); the Python comparison is in OpenSearchParityTest. */
class OpenSearchBackendTest {

    @Test
    void quoteMatchesWhatOpensearchPyProducedForTheSameInput() {
        // value printed by the real opensearch-py 3.2.0 client for "doc1:0 x/\u00e9~,*+"
        assertEquals("doc1%3A0%20x%2F%C3%A9~,*%2B", OpenSearchBackend.quote("doc1:0 x/\u00e9~,*+"));
    }

    @Test
    void isoFormatDropsZeroMicroseconds() {
        OffsetDateTime t = OffsetDateTime.of(2026, 10, 19, 10, 0, 0, 0, ZoneOffset.UTC);
        assertEquals("2026-10-19T10:00:00+00:00", OpenSearchBackend.pyIso(t));
        assertEquals("2026-10-19T10:00:00.123456+00:00", OpenSearchBackend.pyIso(t.withNano(123_456_000)));
    }

    @Test
    void parseUrlDefaultsAndIgnoresTheScheme() {
        assertEquals(new OpenSearchBackend.HostPort("localhost", BigInteger.valueOf(9200)),
                OpenSearchBackend.parseUrl("http://localhost"));
        assertEquals(new OpenSearchBackend.HostPort("UP", BigInteger.ONE), OpenSearchBackend.parseUrl("HTTP://UP:1"));
    }

    @Test
    void pyIntFollowsPythonRules() {
        assertEquals(BigInteger.valueOf(10), OpenSearchBackend.pyInt("1_0"));
        assertEquals(BigInteger.valueOf(-5), OpenSearchBackend.pyInt("-5"));
        assertEquals(BigInteger.valueOf(12), OpenSearchBackend.pyInt(" \uff11\uff12\u00a0"));
        assertThrows(NumberFormatException.class, () -> OpenSearchBackend.pyInt("1__2"));
        assertThrows(NumberFormatException.class, () -> OpenSearchBackend.pyInt("\u200b9200"));
    }

    @Test
    void emptyUrlIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new OpenSearchBackend(""));
        assertThrows(IllegalArgumentException.class, () -> new OpenSearchBackend(null));
    }
}
