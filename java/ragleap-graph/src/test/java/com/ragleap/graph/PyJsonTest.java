package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class PyJsonTest {
    @Test
    void dumpsLikePythonJsonDumps() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("a", 1);
        m.put("b", List.of(1, 2, Map.of("c", 1.5)));
        m.put("d", true);
        m.put("e", null);
        m.put("f", Map.of());
        m.put("g", List.of());
        assertEquals("{\"a\": 1, \"b\": [1, 2, {\"c\": 1.5}], \"d\": true, \"e\": null, \"f\": {}, \"g\": []}",
                PyJson.dumps(m));
    }

    @Test
    void escapesLikeEnsureAscii() {
        assertEquals("\"caf\\u00e9 \\u4e2d \\ud83d\\ude00\"", PyJson.dumps("caf\u00e9 \u4e2d \uD83D\uDE00"));
        assertEquals("\"q\\\" b\\\\ n\\n t\\t \\u0001 \\u007f\"", PyJson.dumps("q\" b\\ n\n t\t \u0001 \u007f"));
    }

    @Test
    void floatReprMatchesPython() {
        assertEquals("1.5", PyJson.floatRepr(1.5));
        assertEquals("0.0001", PyJson.floatRepr(0.0001));
        assertEquals("1e-05", PyJson.floatRepr(1e-05));
        assertEquals("2.5e-07", PyJson.floatRepr(2.5e-07));
        assertEquals("1000000000000000.0", PyJson.floatRepr(1e15));
        assertEquals("1e+16", PyJson.floatRepr(1e16));
        assertEquals("1e+22", PyJson.floatRepr(1e22));
        assertEquals("123456789.123", PyJson.floatRepr(123456789.123));
        assertEquals("-0.0", PyJson.floatRepr(-0.0));
        assertEquals("100.0", PyJson.floatRepr(100.0));
        assertEquals("0.1", PyJson.floatRepr(0.1));
        assertEquals("-1234.5", PyJson.floatRepr(-1234.5));
        assertEquals("30000000000.0", PyJson.floatRepr(3.0e10));
    }

    @Test
    void codePointOrderDiffersFromUtf16Order() {
        String bmpHigh = "\uffffx";
        String supplementary = "\uD800\uDC00x";
        assertTrue(CodePoints.compare(bmpHigh, supplementary) < 0, "code point order: U+FFFF < U+10000");
        assertTrue(bmpHigh.compareTo(supplementary) > 0, "UTF-16 order is the other way round");
        assertTrue(CodePoints.compare("ab", "abc") < 0);
        assertTrue(CodePoints.compare("", "a") < 0);
        assertEquals(0, CodePoints.compare("a", "a"));
        List<String> sorted = new ArrayList<>(List.of("b", "B", "a", supplementary, bmpHigh));
        sorted.sort(CodePoints::compare);
        assertEquals(List.of("B", "a", "b", bmpHigh, supplementary), sorted);
    }
}
