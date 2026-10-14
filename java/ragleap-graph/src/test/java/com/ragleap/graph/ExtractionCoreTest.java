package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Offline tests of the pure extraction parts (hand-computed expectations; the parity tests compare with Python). */
class ExtractionCoreTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final LlmClient STUB = (s, q, t, d, f, temp) -> null;

    @Test
    void ratioKnownValues() {
        assertEquals(1.0, SequenceMatch.ratio("", ""), 0.0);
        assertEquals(0.0, SequenceMatch.ratio("a", ""), 0.0);
        assertEquals(1.0, SequenceMatch.ratio("abc", "abc"), 0.0);
        assertEquals(0.75, SequenceMatch.ratio("abcd", "bcde"), 0.0);
        assertEquals(0.5, SequenceMatch.ratio("ab", "ac"), 0.0);
    }

    @Test
    void ratioCountsCodePointsNotUtf16Units() {
        assertEquals(0.5, SequenceMatch.ratio("\uD83D\uDE00a", "\uD83D\uDE00b"), 0.0);
    }

    @Test
    void normalizeRemovesPunctuationAndCollapsesSpace() {
        assertEquals("acme corpinc", EntityDeduplicator.normalize("  Acme,  Corp.-Inc_ "));
        assertEquals("", EntityDeduplicator.normalize(" . , "));
    }

    @Test
    void resolveMergesVariantsToTheLongestName() {
        Map<String, String> m = new EntityDeduplicator().resolve(List.of("Acme Corp", "ACME Corp.", "Globex"));
        assertEquals("ACME Corp.", m.get("Acme Corp"));
        assertEquals("ACME Corp.", m.get("ACME Corp."));
        assertEquals("Globex", m.get("Globex"));
        assertEquals(List.of("Acme Corp", "ACME Corp.", "Globex"), List.copyOf(m.keySet()));
        assertTrue(new EntityDeduplicator().resolve(List.of()).isEmpty());
    }

    @Test
    void firstLongestNameWinsATie() {
        assertEquals("Acme Co", new EntityDeduplicator().resolve(List.of("Acme Co", "ACME CO")).get("ACME CO"));
    }

    @Test
    void deduplicatorRejectsBadThresholds() {
        for (double t : new double[] {0.0, -1.0, 1.5, Double.NaN}) {
            IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> new EntityDeduplicator(t));
            assertEquals("threshold must be in (0.0, 1.0]", e.getMessage());
        }
        new EntityDeduplicator(1.0);
    }

    @Test
    void configDefaultsAndValidationOrder() {
        ExtractionConfig d = ExtractionConfig.regex();
        assertEquals(ExtractionConfig.Method.REGEX, d.method());
        assertEquals(0.92, d.dedupThreshold(), 0.0);
        assertEquals(25, d.maxEntitiesPerChunk());
        assertFalse(d.dedupEnabled());
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> ExtractionConfig.builder().extractRelations(true).dedupThreshold(5.0).build());
        assertTrue(e.getMessage().startsWith("extract_relations=True requires method='llm'"));
        e = assertThrows(IllegalArgumentException.class,
                () -> ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).build());
        assertTrue(e.getMessage().startsWith("ExtractionConfig(method='llm') requires llm=..."));
        ExtractionConfig ok = ExtractionConfig.builder().method(ExtractionConfig.Method.LLM).llm(STUB)
                .extractRelations(true).crossChunkRelations(true).build();
        assertTrue(ok.crossChunkRelations());
    }

    @Test
    void reprFollowsPython() throws Exception {
        assertEquals("\"it's\"", PyRepr.str("it's"));
        assertEquals("'a\\'b\"c'", PyRepr.str("a'b\"c"));
        assertEquals("'tab\\t'", PyRepr.str("tab\t"));
        assertEquals("'\\x01'", PyRepr.str("\u0001"));
        assertEquals("{'a': [1, 2.5, None, True]}", PyRepr.of(MAPPER.readTree("{\"a\":[1,2.5,null,true]}")));
        assertEquals("None", PyRepr.strOf(MAPPER.readTree("null")));
        assertEquals("plain", PyRepr.strOf(MAPPER.readTree("\"plain\"")));
        assertEquals("1e+20", PyRepr.strOf(MAPPER.readTree("1e20")));
    }
}
