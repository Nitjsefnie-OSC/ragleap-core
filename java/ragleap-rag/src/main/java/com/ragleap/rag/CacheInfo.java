package com.ragleap.rag;

/** Query embedding cache statistics; all zeros when the cache is disabled. */
public record CacheInfo(long hits, long misses, double hitRate, int size, boolean enabled) {
}
