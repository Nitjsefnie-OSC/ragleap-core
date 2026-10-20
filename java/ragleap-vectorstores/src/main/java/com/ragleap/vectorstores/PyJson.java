package com.ragleap.vectorstores;

import java.math.BigDecimal;
import java.util.Map;

/**
 * Serialization compatible with Python's json.dumps(obj, default=str): default separators, ensure_ascii, Python
 * float formatting. Floats are exact for normal (non-subnormal) doubles; other unknown types use toString().
 */
final class PyJson {
    private PyJson() {
    }

    static String dumps(Object value) {
        StringBuilder sb = new StringBuilder();
        write(sb, value);
        return sb.toString();
    }

    private static void write(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof Boolean b) {
            sb.append(b ? "true" : "false");
        } else if (v instanceof String s) {
            string(sb, s);
        } else if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            if (Double.isNaN(d)) {
                sb.append("NaN");
            } else if (Double.isInfinite(d)) {
                sb.append(d > 0 ? "Infinity" : "-Infinity");
            } else {
                sb.append(floatRepr(d));
            }
        } else if (v instanceof Number n) {
            sb.append(n);
        } else if (v instanceof Map<?, ?> m) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (!first) {
                    sb.append(", ");
                }
                first = false;
                string(sb, String.valueOf(e.getKey()));
                sb.append(": ");
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof Iterable<?> it) {
            sb.append('[');
            boolean first = true;
            for (Object e : it) {
                if (!first) {
                    sb.append(", ");
                }
                first = false;
                write(sb, e);
            }
            sb.append(']');
        } else {
            string(sb, String.valueOf(v));
        }
    }

    private static void string(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20 || c > 0x7e) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        sb.append('"');
    }

    /** Python's repr(float) (also used by str(float)). */
    static String floatRepr(double d) {
        if (Double.isNaN(d)) {
            return "nan";
        }
        if (Double.isInfinite(d)) {
            return d > 0 ? "inf" : "-inf";
        }
        if (d == 0.0) {
            return (1.0 / d < 0) ? "-0.0" : "0.0";
        }
        BigDecimal bd = new BigDecimal(Double.toString(Math.abs(d))).stripTrailingZeros();
        String digits = bd.unscaledValue().toString();
        int decpt = digits.length() - bd.scale();
        StringBuilder sb = new StringBuilder(d < 0 ? "-" : "");
        if (decpt <= -4 || decpt > 16) {
            sb.append(digits.charAt(0));
            if (digits.length() > 1) {
                sb.append('.').append(digits, 1, digits.length());
            }
            int e = decpt - 1;
            sb.append('e').append(e < 0 ? '-' : '+');
            int ae = Math.abs(e);
            if (ae < 10) {
                sb.append('0');
            }
            sb.append(ae);
        } else if (decpt <= 0) {
            sb.append("0.");
            for (int i = 0; i < -decpt; i++) {
                sb.append('0');
            }
            sb.append(digits);
        } else if (decpt >= digits.length()) {
            sb.append(digits);
            for (int i = digits.length(); i < decpt; i++) {
                sb.append('0');
            }
            sb.append(".0");
        } else {
            sb.append(digits, 0, decpt).append('.').append(digits, decpt, digits.length());
        }
        return sb.toString();
    }
}
