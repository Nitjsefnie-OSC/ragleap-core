package com.ragleap.graph;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Iterator;
import java.util.Map;

/**
 * Python repr() and str() of the values json.loads produces. Printable characters follow the Unicode data of the
 * running JVM (Python uses its own Unicode version), so characters assigned only in recent Unicode releases can differ.
 */
final class PyRepr {
    private PyRepr() {
    }

    /** repr() of a Python str. */
    static String str(String s) {
        boolean hasSingle = s.indexOf('\'') >= 0;
        boolean hasDouble = s.indexOf('"') >= 0;
        char quote = (hasSingle && !hasDouble) ? '"' : '\'';
        StringBuilder sb = new StringBuilder();
        sb.append(quote);
        for (int i = 0; i < s.length();) {
            int cp = s.codePointAt(i);
            i += Character.charCount(cp);
            if (cp == quote || cp == '\\') {
                sb.append('\\').appendCodePoint(cp);
            } else if (cp == '\t') {
                sb.append("\\t");
            } else if (cp == '\n') {
                sb.append("\\n");
            } else if (cp == '\r') {
                sb.append("\\r");
            } else if (cp < 0x20 || cp == 0x7f) {
                sb.append(String.format("\\x%02x", cp));
            } else if (cp < 0x7f) {
                sb.append((char) cp);
            } else if (isPrintable(cp)) {
                sb.appendCodePoint(cp);
            } else if (cp <= 0xff) {
                sb.append(String.format("\\x%02x", cp));
            } else if (cp <= 0xffff) {
                sb.append(String.format("\\u%04x", cp));
            } else {
                sb.append(String.format("\\U%08x", cp));
            }
        }
        sb.append(quote);
        return sb.toString();
    }

    /** Python's str.isprintable() for one character (space is printable). */
    static boolean isPrintable(int cp) {
        if (cp == ' ') {
            return true;
        }
        int t = Character.getType(cp);
        return !(t == Character.CONTROL || t == Character.FORMAT || t == Character.SURROGATE
                || t == Character.PRIVATE_USE || t == Character.UNASSIGNED || t == Character.LINE_SEPARATOR
                || t == Character.PARAGRAPH_SEPARATOR || t == Character.SPACE_SEPARATOR);
    }

    /** repr() of a parsed JSON value. */
    static String of(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return "None";
        }
        if (n.isBoolean()) {
            return n.asBoolean() ? "True" : "False";
        }
        if (n.isIntegralNumber()) {
            return n.bigIntegerValue().toString();
        }
        if (n.isNumber()) {
            return PyJson.floatRepr(n.doubleValue());
        }
        if (n.isTextual()) {
            return str(n.asText());
        }
        StringBuilder sb = new StringBuilder();
        boolean first = true;
        if (n.isArray()) {
            sb.append('[');
            for (JsonNode e : n) {
                if (!first) {
                    sb.append(", ");
                }
                first = false;
                sb.append(of(e));
            }
            return sb.append(']').toString();
        }
        sb.append('{');
        Iterator<Map.Entry<String, JsonNode>> it = n.fields();
        while (it.hasNext()) {
            Map.Entry<String, JsonNode> e = it.next();
            if (!first) {
                sb.append(", ");
            }
            first = false;
            sb.append(str(e.getKey())).append(": ").append(of(e.getValue()));
        }
        return sb.append('}').toString();
    }

    /** str() of a parsed JSON value: strings as they are, everything else as repr(). */
    static String strOf(JsonNode n) {
        return n != null && n.isTextual() ? n.asText() : of(n);
    }

    /** Python type name of a parsed JSON value. */
    static String typeName(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return "NoneType";
        }
        if (n.isBoolean()) {
            return "bool";
        }
        if (n.isIntegralNumber()) {
            return "int";
        }
        if (n.isNumber()) {
            return "float";
        }
        if (n.isTextual()) {
            return "str";
        }
        return n.isArray() ? "list" : "dict";
    }
}
