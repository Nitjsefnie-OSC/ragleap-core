package com.ragleap.graph;

import java.util.Map;
import java.util.Set;

/**
 * json.dumps(detail) as the Python audit logger calls it: no default function, so a value that is not a map, list,
 * string, number, boolean or null raises (TypeError in Python, IllegalArgumentException here). A Java Set is rejected
 * like a Python set, and so are arrays.
 */
final class AuditJson {
    private AuditJson() {
    }

    static String dumps(Object value) {
        check(value);
        return PyJson.dumps(value);
    }

    private static void check(Object v) {
        if (v == null || v instanceof Boolean || v instanceof String || v instanceof Number) {
            return;
        }
        if (v instanceof Map<?, ?> m) {
            for (Object e : m.values()) {
                check(e);
            }
            return;
        }
        if (v instanceof Iterable<?> it && !(v instanceof Set)) {
            for (Object e : it) {
                check(e);
            }
            return;
        }
        throw new IllegalArgumentException("Object of type " + v.getClass().getSimpleName()
                + " is not JSON serializable");
    }
}
