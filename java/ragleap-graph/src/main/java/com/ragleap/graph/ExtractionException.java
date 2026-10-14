package com.ragleap.graph;

/**
 * A failure of LLM extraction. pythonType() names the exception the Python package raises in the same situation
 * (ValueError, RuntimeError, AttributeError, TypeError), so behaviour can be compared one to one.
 */
public final class ExtractionException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    private final String pythonType;

    public ExtractionException(String pythonType, String message) {
        super(message);
        this.pythonType = pythonType;
    }

    public String pythonType() {
        return pythonType;
    }
}
