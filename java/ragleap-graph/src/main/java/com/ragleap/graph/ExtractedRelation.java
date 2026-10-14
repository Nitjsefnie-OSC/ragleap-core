package com.ragleap.graph;

/** A single typed relation between two known entities. */
public record ExtractedRelation(String subject, String relationType, String object) {
}
