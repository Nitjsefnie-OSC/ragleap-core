package com.ragleap.rag;

/** Query rewrite strategies for {@link RagLeap#ask}. */
public enum QueryRewrite {
    CONTEXTUAL("contextual"),
    HYDE("hyde"),
    MULTI_QUERY("multi_query");

    private final String id;

    QueryRewrite(String id) {
        this.id = id;
    }

    /** The strategy name as the Python package spells it. */
    public String id() {
        return id;
    }
}
