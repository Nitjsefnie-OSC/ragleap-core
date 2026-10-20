# ragleap-vectorstores (Java)

Java port of [ragleap-vectorstores](https://pypi.org/project/ragleap-vectorstores/): extra vector store backends for
[ragleap-rag](../ragleap-rag). Every backend implements ragleap-rag's `VectorBackend` interface and talks to its store
over REST with the JDK `HttpClient` and Jackson, with no vendor SDK.

**Status: work in progress, not published to Maven Central yet.** OpenSearch and Upstash exist so far.

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
# regenerate fixtures (needs the pinned Python package and a venv with opensearch-py 3.2.0 and upstash-vector 0.8.0)
VS_PIN=078ca87 python parity/gen_fixtures_opensearch.py
VS_PIN=078ca87 python parity/gen_fixtures_upstash.py
RAGLEAP_VS_PARITY_DIR=/root/fixtures-vs mvn -B test
```

Without `RAGLEAP_VS_PARITY_DIR` the parity tests are skipped (this is what CI runs).

## Upstash

```java
UpstashBackend backend = new UpstashBackend("https://YOUR-INDEX.upstash.io", token);
// optional: new UpstashBackend(url, token, "my-namespace", "/path/to/registry.sqlite3")
```

(Snippet not compiled.) The index must already exist as a pure dense index (create it in the Upstash console);
`initSchema` only checks it. Chunk text and metadata live in Upstash; the document registry (filename and upload
time) is a local SQLite file, by default `~/.ragleap_vectorstores/upstash_documents.sqlite3`. Use a distinct
namespace for each separate deployment that shares one index. Scores are Upstash's own, already in [0, 1]; no sparse
search.

### Differences from Python

- No retry on connection failures (the Python SDK retries 3 times, 1 s apart); 30 s request timeout (SDK: 600 s).
- The url is used exactly as given, like the SDK (no scheme is added; a trailing slash gives `//info`).
- A namespace is sent percent-encoded; the SDK leaves a few characters raw that `java.net.URI` cannot send
  (invalid percent escapes, square brackets, `|`, `^`). Those two scenarios compare the decoded path.
- A filter value that is a list or map throws; a missing or non-numeric `chunk_index` comes back as 0.
- Failures throw `SQLException`; a wrong dimension or a hybrid index throws `IllegalStateException`.

Copied from Python on purpose (possible Python issues, not fixed here): the chunk count in `listDocuments` is capped
at the first 1000 chunks of a document; `deleteDocument` deletes by the prefix `<id>:`, so a document id that
contains a colon can collide with another document's chunks; caller metadata keys override the stored `text` and
`document_id`.

### How it was verified

Recorded-request parity against the real Python `UpstashBackend`, the real upstash-vector 0.8.0 SDK and a real SQLite
registry: 33 scripted scenarios (60 requests). 31 are compared request by request and result by result (57
requests); one (url with a trailing slash) is checked by a raw-socket test that reads the literal request line;
one is skipped because Python's own HTTP client rejects it (a tab in the namespace). Fifteen deliberate breaks of the
Java code were each caught by the tests. **Not live-verified:** no real Upstash index was used.

## Not ported yet

Redis, Chroma and LanceDB.
