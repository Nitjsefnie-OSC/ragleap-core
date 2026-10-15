# ragleap-graph (Java)

Java port of the Python package `packages/ragleap-graph` (knowledge-graph-augmented retrieval for RAG), published on Maven Central:

```xml
<dependency>
    <groupId>io.github.antonyrag</groupId>
    <artifactId>ragleap-graph</artifactId>
    <version>0.2.0</version>
</dependency>
```

It is versioned independently from the Python package. It talks to Neo4j over its HTTP Query API, with no Neo4j driver dependency; the only required runtime dependency is jackson-databind. Only Neo4j 5.26 Community, single server, has been tested.

## What is included

- Entity extraction: regex (the default) or, optionally, an LLM through a small `LlmClient` interface (`LlmEntityExtractor`, `LlmRelationExtractor`, `ExtractionConfig`), with entity deduplication (`EntityDeduplicator`).
- `GraphIndex`: `upsertDocument` (per-document weights, co-occurrence edges, typed relations), and the lookups `findDocumentsByEntities`, `documentEntities`, `searchRelatedEntities`, `findRelations`, `findLineage`, `findEntitiesByType`. If the server cannot be reached, the index is unavailable and the lookups return empty results, like the Python package.
- `GraphRetriever` and `GraphRetrievalConfig`: hybrid (vector plus graph) or graph-only retrieval with chunk and graph-path citations.
- One-time backfills on `GraphIndex` and a schema migration runner (`Migration`, `MigrationRunner`).
- Optional adapters over `ragleap-rag` (add `io.github.antonyrag:ragleap-rag` to your own project to use them): `RagLeapGenerationClient` for LLM extraction and `RagLeapVectorSearch` for the vector side of retrieval.

## Quick start

```java
GraphConfig config = new GraphConfig("http://localhost:7474", "neo4j", "password");
try (GraphIndex graph = new GraphIndex(config)) {
    graph.upsertDocument("doc-1", "Partnership news",
            List.of(Map.of("text", "Acme Corp announced a partnership with Globex Industries.")), "my-namespace");

    RetrievalResult result = new GraphRetriever(graph, null,
            GraphRetrievalConfig.builder().mode(GraphRetrievalConfig.Mode.GRAPH_ONLY).build())
            .retrieve("What do Acme Corp and Globex Industries share?", 5, "my-namespace", null);
    System.out.println(result.graphContext().relatedDocuments());
}
```

For hybrid retrieval, pass a `VectorSearch` (for example `RagLeapVectorSearch.of(rag)`) as the second argument.

LLM extraction needs a model client. With `ragleap-rag` on your classpath:

```java
LlmClient llm = RagLeapGenerationClient.of(providerConfig); // providerConfig: a ragleap-rag ProviderConfig
ExtractionConfig extraction = ExtractionConfig.builder()
        .method(ExtractionConfig.Method.LLM).llm(llm)
        .extractRelations(true).dedupEnabled(true).build();
GraphIndex graph = new GraphIndex(config, extraction);
```

## Not live-verified

- LLM extraction against a real model provider: it is tested with scripted model answers and a local fake OpenAI-style server only.
- Any Neo4j other than 5.26.29 Community, single server (bookmarks are not passed along).
- `RagLeapVectorSearch.of(RagLeap)` against a live ragleap-rag facade (its conversion and error handling are tested with a stand-in).

## Not ported yet

- The Postgres audit writer (a no-op audit sink is the default).

## Tests and parity

`mvn -B test` runs the offline tests; parity and live tests skip when their environment is not set.

Parity: outputs are compared with recordings generated from the real Python code at commit 226fa4de (the nine scripts `parity/gen_fixtures_*.py`). To run them:

```bash
mkdir -p /tmp/py-graph-pinned
git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
for s in java/ragleap-graph/parity/gen_fixtures_*.py; do python3 "$s"; done
cd java/ragleap-graph && RAGLEAP_GRAPH_PARITY_DIR=/tmp/fixtures-graph-a mvn -B test
```

Live tests need `NEO4J_HTTP_URL`, `NEO4J_USER` and `NEO4J_PASSWORD` (a Neo4j server with the HTTP Query API) and use their own unique namespaces, which they remove afterwards.
