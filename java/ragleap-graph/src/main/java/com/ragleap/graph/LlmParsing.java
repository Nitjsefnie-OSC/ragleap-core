package com.ragleap.graph;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.json.JsonReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.util.ArrayList;
import java.util.List;

/**
 * Parsing of model answers the way the Python extractors do it: json.loads rules (NaN and Infinity accepted, text
 * after the value rejected, an empty string rejected), str() of whatever the model put in a field, and the errors
 * Python raises when the answer has an unexpected shape (reported through ExtractionException with the Python type).
 */
final class LlmParsing {
    private static final ObjectMapper LOADS = JsonMapper.builder()
            .enable(JsonReadFeature.ALLOW_NON_NUMERIC_NUMBERS)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .build();
    private static final ObjectMapper PLAIN = new ObjectMapper();

    private LlmParsing() {
    }

    static JsonNode schema(String json) {
        try {
            return PLAIN.readTree(json);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    /** json.loads; null when Python would raise JSONDecodeError (a null answer counts as an empty string). */
    static JsonNode loads(String s) {
        try {
            JsonNode n = LOADS.readTree(s == null ? "" : s);
            return n == null || n.isMissingNode() ? null : n;
        } catch (JsonProcessingException e) {
            return null;
        }
    }

    /** Python f"{value}" of a str that may be None. */
    static String none(String s) {
        return s == null ? "None" : s;
    }

    /** Python repr() of a str that may be None. */
    static String reprOrNone(String s) {
        return s == null ? "None" : PyRepr.str(s);
    }

    private static JsonNode field(JsonNode obj, String key) {
        if (obj == null || !obj.isObject()) {
            return null;
        }
        JsonNode v = obj.get(key);
        return v == null || v.isNull() ? null : v;
    }

    /** The structured answer when valid, else the answer text parsed as JSON; null means "malformed". */
    static JsonNode listField(LlmResult r, String key) {
        JsonNode raw = field(Boolean.TRUE.equals(r.structuredValid()) ? r.structured() : null, key);
        if (raw == null) {
            raw = field(loads(r.answer()), key);
        }
        return raw;
    }

    private static ExtractionException noGet(JsonNode item) {
        return new ExtractionException("AttributeError",
                "'" + PyRepr.typeName(item) + "' object has no attribute 'get'");
    }

    private static ExtractionException strItem() {
        return new ExtractionException("AttributeError", "'str' object has no attribute 'get'");
    }

    /** Python: raw[:max] followed by item.get(...) on every item. */
    static List<JsonNode> sliceItems(JsonNode raw, int max) {
        List<JsonNode> items = new ArrayList<>();
        if (raw.isArray()) {
            int limit = Math.min(max, raw.size());
            for (int i = 0; i < limit; i++) {
                JsonNode item = raw.get(i);
                if (!item.isObject()) {
                    throw noGet(item);
                }
                items.add(item);
            }
            return items;
        }
        if (raw.isTextual()) {
            if (raw.asText().isEmpty()) {
                return items;
            }
            throw strItem();
        }
        if (raw.isObject()) {
            throw new ExtractionException("TypeError", "unhashable type: 'slice'");
        }
        throw new ExtractionException("TypeError", "'" + PyRepr.typeName(raw) + "' object is not subscriptable");
    }

    /** Python: for item in raw, then item.get(...) (a dict iterates its keys, a str its characters). */
    static List<JsonNode> iterItems(JsonNode raw) {
        List<JsonNode> items = new ArrayList<>();
        if (raw.isArray()) {
            for (JsonNode item : raw) {
                if (!item.isObject()) {
                    throw noGet(item);
                }
                items.add(item);
            }
            return items;
        }
        if (raw.isTextual() || raw.isObject()) {
            boolean empty = raw.isTextual() ? raw.asText().isEmpty() : raw.size() == 0;
            if (empty) {
                return items;
            }
            throw strItem();
        }
        throw new ExtractionException("TypeError", "'" + PyRepr.typeName(raw) + "' object is not iterable");
    }

    /** Python: str(item.get(key, dflt)). A JSON null becomes the text "None". */
    static String str(JsonNode item, String key, String dflt) {
        return item.has(key) ? PyRepr.strOf(item.get(key)) : dflt;
    }
}
