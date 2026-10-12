package com.ragleap.rag;

import java.util.List;

/**
 * What a rewrite strategy produced. Only the field belonging to the strategy is set: rewrittenQuery for
 * "contextual", hydeDocument for "hyde", queryVariants for "multi_query".
 */
public record QueryRewriteInfo(String strategy, String rewrittenQuery, String hydeDocument,
                               List<String> queryVariants) {
}
