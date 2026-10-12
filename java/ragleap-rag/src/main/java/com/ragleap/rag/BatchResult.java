package com.ragleap.rag;

import com.ragleap.rag.ingestion.IngestResult;

/** Outcome of one item of {@link RagLeap#ingestBatch}: result is set on success, error on failure. */
public record BatchResult(boolean success, IngestResult result, String error) {
}
