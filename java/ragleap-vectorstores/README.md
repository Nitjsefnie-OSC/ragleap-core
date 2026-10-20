# ragleap-vectorstores (Java)

Java port of [ragleap-vectorstores](https://pypi.org/project/ragleap-vectorstores/): extra vector store backends for
[ragleap-rag](../ragleap-rag). Every backend implements ragleap-rag's `VectorBackend` interface and talks to its store
over REST with the JDK `HttpClient` and Jackson, with no vendor SDK.

**Status: work in progress, not published to Maven Central yet.** Only OpenSearch exists so far.

## OpenSearch

```java
OpenSearchBackend backend = new OpenSearchBackend("http://localhost:9200");
RagLeapConfig config = RagLeapConfig.builder(databaseUrl, provider, embeddingConfig).vectorBackend(backend).build();
```

(Snippet not compiled; check names against the ragleap-rag javadoc.)

- Index with an HNSW k-NN field (engine lucene, cosine); the document registry is a second index named
  `<index>_documents`.
- Scores are OpenSearch's own, already in [0, 1]; no sparse search (`supportsSparse()` is false).
- Constructor options: index name, documents index name, `useSsl`, basic authentication, your own `HttpClient`.

### Differences from Python

- TLS certificates are verified by default (Python's `verify_certs` defaults to false). Pass your own `HttpClient`
  for custom trust.
- Only basic authentication and `use_ssl` are supported, not opensearch-py's `client_kwargs`.
- Like Python, the URL scheme is ignored: only `useSsl` chooses http or https.
- Failures throw `SQLException` (Python: `TransportError`); a dimension mismatch throws `IllegalStateException`
  (Python: `RuntimeError`).

### How it was verified

Recorded-request parity: the real Python `OpenSearchBackend` with the real opensearch-py 3.2.0 client runs against a
fake HTTP server that records every request; the Java backend runs the same 29 scripted scenarios against a JDK fake
server and must send identical requests (method, path, query, body, auth) and return identical results. Ten
deliberate breaks of the Java code were each caught by the tests.

**Not live-verified:** no real OpenSearch server was used. Python was pinned at commit `078ca87`.

```bash
# regenerate fixtures (needs the pinned Python package and a venv with opensearch-py 3.2.0), then run all tests
VS_PIN=078ca87 python parity/gen_fixtures_opensearch.py
RAGLEAP_VS_PARITY_DIR=/root/fixtures-vs mvn -B test
```

Without `RAGLEAP_VS_PARITY_DIR` the parity tests are skipped (this is what CI runs).

## Not ported yet

Upstash, Redis, Chroma and LanceDB.
