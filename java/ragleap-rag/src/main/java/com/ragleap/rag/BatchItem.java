package com.ragleap.rag;

import com.ragleap.rag.ingestion.TranscriptionConfig;
import java.util.Map;

/** One item for {@link RagLeap#ingestBatch}. Create items with the static factories. */
public record BatchItem(Kind kind, String filename, byte[] rawBytes, String mode, String mimeType,
                        TranscriptionConfig transcriber, Map<String, Object> metadata) {

    public enum Kind { FILE, IMAGE, AUDIO, VIDEO }

    public static BatchItem file(String filename, byte[] rawBytes) {
        return file(filename, rawBytes, null);
    }

    public static BatchItem file(String filename, byte[] rawBytes, Map<String, Object> metadata) {
        return new BatchItem(Kind.FILE, filename, rawBytes, null, null, null, metadata);
    }

    public static BatchItem image(String filename, byte[] rawBytes) {
        return image(filename, rawBytes, "ocr", "image/jpeg", null);
    }

    public static BatchItem image(String filename, byte[] rawBytes, String mode) {
        return image(filename, rawBytes, mode, "image/jpeg", null);
    }

    public static BatchItem image(String filename, byte[] rawBytes, String mode, String mimeType,
                                  Map<String, Object> metadata) {
        return new BatchItem(Kind.IMAGE, filename, rawBytes, mode, mimeType, null, metadata);
    }

    public static BatchItem audio(String filename, byte[] rawBytes, TranscriptionConfig transcriber,
                                  Map<String, Object> metadata) {
        return new BatchItem(Kind.AUDIO, filename, rawBytes, null, null, transcriber, metadata);
    }

    public static BatchItem video(String filename, byte[] rawBytes, TranscriptionConfig transcriber,
                                  Map<String, Object> metadata) {
        return new BatchItem(Kind.VIDEO, filename, rawBytes, null, null, transcriber, metadata);
    }
}
