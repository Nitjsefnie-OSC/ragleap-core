package com.ragleap.graph;

/** A single extracted entity, typed ("UNKNOWN" when there is no reliable type). */
public record ExtractedEntity(String name, String type) {
    public ExtractedEntity(String name) {
        this(name, "UNKNOWN");
    }
}
