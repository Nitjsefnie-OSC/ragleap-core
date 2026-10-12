package com.ragleap.rag;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.NullNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ragleap.rag.cache.QueryEmbeddingCache;
import com.ragleap.rag.cost.CostTracker;
import com.ragleap.rag.evaluation.CaseResult;
import com.ragleap.rag.evaluation.EvalCase;
import com.ragleap.rag.evaluation.EvaluationResult;
import com.ragleap.rag.generation.Citation;
import com.ragleap.rag.generation.GenerationResult;
import com.ragleap.rag.generation.GenerationService;
import com.ragleap.rag.generation.ProviderConfig;
import com.ragleap.rag.generation.Usage;
import com.ragleap.rag.guardrails.GuardrailViolation;
import com.ragleap.rag.memory.ConversationMemory;
import com.ragleap.rag.vectorstore.DocumentSummary;
import com.ragleap.rag.vectorstore.SearchResult;
import com.ragleap.rag.vectorstore.VectorBackend;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.UnaryOperator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Runs the same scenarios as the real Python RagLeap class (fixtures from parity/gen_facade_fixtures.py) over fake
 * collaborators and compares the whole ordered log of collaborator calls, hook events and memory writes, plus the
 * returned values.
 */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_FACADE_PARITY_DIR", matches = ".+")
class RagLeapParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Map<String, UnaryOperator<String>> GUARDS = Map.of(
            "replace_foo", t -> t.replace("foo", "bar"),
            "block_forbidden", t -> {
                if (t.contains("forbidden")) {
                    throw new GuardrailViolation("contains forbidden text");
                }
                return t;
            });

    static String canon(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return "null";
        }
        if (n.isObject()) {
            List<String> keys = new ArrayList<>();
            n.fieldNames().forEachRemaining(keys::add);
            Collections.sort(keys);
            StringBuilder sb = new StringBuilder("{");
            for (String k : keys) {
                sb.append(k.length()).append(':').append(k).append('=').append(canon(n.get(k))).append(',');
            }
            return sb.append('}').toString();
        }
        if (n.isArray()) {
            StringBuilder sb = new StringBuilder("[");
            for (JsonNode e : n) {
                sb.append(canon(e)).append(',');
            }
            return sb.append(']').toString();
        }
        if (n.isIntegralNumber()) {
            return "i" + n.bigIntegerValue();
        }
        if (n.isFloatingPointNumber()) {
            return "f" + n.doubleValue();
        }
        if (n.isBoolean()) {
            return "b" + n.booleanValue();
        }
        return "s" + n.asText().length() + ":" + n.asText();
    }

    private static ObjectNode obj() {
        return MAPPER.createObjectNode();
    }

    private static JsonNode tree(Object o) {
        return o == null ? NullNode.getInstance() : MAPPER.valueToTree(o);
    }

    private static String text(JsonNode n) {
        return n == null || n.isNull() ? null : n.asText();
    }

    private static List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        if (n != null) {
            for (JsonNode e : n) {
                out.add(e.asText());
            }
        }
        return out;
    }

    private static void putText(ObjectNode o, String key, String v) {
        if (v == null) {
            o.putNull(key);
        } else {
            o.put(key, v);
        }
    }

    private static void putNum(ObjectNode o, String key, Double v) {
        if (v == null) {
            o.putNull(key);
        } else {
            o.put(key, v.doubleValue());
        }
    }

    private static ProviderConfig provider(String model) {
        return new ProviderConfig("openai", "key", model, "http://localhost:1/v1");
    }

    private static Map<String, Object> filter(JsonNode n) {
        if (n == null || n.isNull()) {
            return null;
        }
        return MAPPER.convertValue(n, new TypeReference<Map<String, Object>>() { });
    }

    static final class FakeBackend implements VectorBackend {
        private final JsonNode results;
        private final List<String> log;

        FakeBackend(JsonNode results, List<String> log) {
            this.results = results;
            this.log = log;
        }

        private List<SearchResult> scripted(String key) {
            JsonNode arr = results.has(key) ? results.get(key) : results.get("default");
            List<SearchResult> out = new ArrayList<>();
            if (arr != null) {
                for (JsonNode c : arr) {
                    out.add(new SearchResult(c.get("chunk_id").asText(), c.get("text").asText(),
                            c.get("similarity_score").asDouble(), c.get("document_id").asText(),
                            c.get("document_name").asText(), c.get("chunk_index").asInt(),
                            c.get("retrieval_method").asText()));
                }
            }
            return out;
        }

        @Override
        public List<SearchResult> searchHybrid(String queryText, List<Double> embedding, int topK,
                                               Map<String, Object> metadataFilter) {
            ObjectNode e = obj();
            e.put("c", "hybrid");
            e.put("q", queryText);
            e.set("emb", tree(embedding));
            e.put("top_k", topK);
            e.set("filter", tree(metadataFilter));
            log.add(canon(e));
            return scripted(queryText);
        }

        @Override
        public List<SearchResult> searchDense(List<Double> embedding, int topK, Map<String, Object> metadataFilter) {
            ObjectNode e = obj();
            e.put("c", "dense");
            e.set("emb", tree(embedding));
            e.put("top_k", topK);
            e.set("filter", tree(metadataFilter));
            log.add(canon(e));
            return scripted("len" + (int) embedding.get(0).doubleValue());
        }

        @Override
        public void initSchema(int dimensions) {
        }

        @Override
        public void insertDocument(String documentId, String filename, Map<String, Object> metadata) {
        }

        @Override
        public void insertChunk(String documentId, String documentName, int chunkIndex, String text,
                                Integer tokenCount, List<Double> embedding, Map<String, Object> metadata) {
        }

        @Override
        public List<DocumentSummary> listDocuments(int limit, int offset) {
            return List.of();
        }

        @Override
        public boolean deleteDocument(String documentId) {
            return false;
        }

        @Override
        public Optional<String> getDocumentFilename(String documentId) {
            return Optional.empty();
        }
    }

    static final class FakeMemory extends ConversationMemory {
        private final String history;
        private final List<String> log;

        FakeMemory(String history, List<String> log) {
            super(null);
            this.history = history;
            this.log = log;
        }

        @Override
        public String buildHistoryPrompt(String sessionId) {
            ObjectNode e = obj();
            e.put("c", "mem_build");
            e.put("session", sessionId);
            log.add(canon(e));
            return history;
        }

        @Override
        public void addMessage(String sessionId, String role, String content) {
            ObjectNode e = obj();
            e.put("c", "mem_add");
            e.put("session", sessionId);
            e.put("role", role);
            e.put("content", content);
            log.add(canon(e));
        }
    }

    static final class FakeGenerator extends GenerationService {
        private static final String[][] MARKERS = {
            {"contextual", "standalone question"}, {"hyde", "plausible passage"}, {"multi", "different phrasings"}};
        private final JsonNode script;
        private final List<String> pieces;
        private final List<String> log;
        private final ProviderConfig fallback;

        FakeGenerator(JsonNode script, List<String> pieces, List<String> log, ProviderConfig fallback) {
            super(provider("primary-model"));
            this.script = script;
            this.pieces = pieces;
            this.log = log;
            this.fallback = fallback;
        }

        private ObjectNode entry(String kind, String query, List<SearchResult> chunks, Double temperature,
                                 ProviderConfig override, Integer maxTokens, String historyPrefix,
                                 String systemPrompt) {
            ObjectNode e = obj();
            e.put("c", kind);
            e.put("query", query);
            ArrayNode ids = MAPPER.createArrayNode();
            for (SearchResult c : chunks) {
                ids.add(c.chunkId());
            }
            e.set("chunk_ids", ids);
            if (temperature == null) {
                e.putNull("temperature");
            } else {
                e.put("temperature", temperature.doubleValue());
            }
            putText(e, "system_prompt", systemPrompt);
            if (maxTokens == null) {
                e.putNull("max_tokens");
            } else {
                e.put("max_tokens", maxTokens.intValue());
            }
            e.put("history_prefix", historyPrefix == null ? "" : historyPrefix);
            if (override != null && override == fallback) {
                e.put("override", "fallback");
            } else {
                e.putNull("override");
            }
            return e;
        }

        @Override
        public GenerationResult generateAnswer(String query, List<SearchResult> chunks, Double temperature,
                                               ProviderConfig overrideProvider, Integer maxTokens,
                                               String historyPrefix, String systemPromptOverride,
                                               com.fasterxml.jackson.databind.JsonNode responseFormat) {
            ObjectNode e = entry("gen", query, chunks, temperature, overrideProvider, maxTokens, historyPrefix,
                    systemPromptOverride);
            e.set("response_format", responseFormat == null ? NullNode.getInstance() : responseFormat);
            log.add(canon(e));
            String key = "answer";
            for (String[] m : MARKERS) {
                if ((systemPromptOverride != null && systemPromptOverride.contains(m[1]))
                        || (query != null && query.contains(m[1]))) {
                    key = m[0];
                    break;
                }
            }
            return toResult(script.get(key));
        }

        @Override
        public void generateAnswerStream(String query, List<SearchResult> chunks, Double temperature,
                                         ProviderConfig overrideProvider, Integer maxTokens, String historyPrefix,
                                         String systemPromptOverride, Consumer<String> onPiece) {
            log.add(canon(entry("stream", query, chunks, temperature, overrideProvider, maxTokens, historyPrefix,
                    systemPromptOverride)));
            for (String piece : pieces) {
                onPiece.accept(piece);
            }
        }

        private static GenerationResult toResult(JsonNode r) {
            List<Citation> cits = new ArrayList<>();
            for (JsonNode c : r.get("citations")) {
                cits.add(new Citation(c.get("source_number").asInt(), c.get("document_name").asText(),
                        c.get("document_id").asText(), c.get("chunk_id").asText(), c.get("chunk_index").asInt(),
                        c.get("text_preview").asText()));
            }
            JsonNode u = r.get("usage");
            Usage usage = u.isNull() ? null : new Usage(u.get("prompt_tokens").asInt(),
                    u.get("completion_tokens").asInt(), u.get("total_tokens").asInt());
            return new GenerationResult(r.get("answer").asText(), strings(r.get("sources")), cits,
                    text(r.get("provider_used")), text(r.get("model_used")), usage, r.get("chunks_sent").asInt(),
                    r.has("structured") ? r.get("structured") : null,
                    r.has("structured_valid") ? r.get("structured_valid").asBoolean() : null,
                    r.has("structured_enforcement") ? r.get("structured_enforcement").asText() : null, null);
        }
    }

    private static AskOptions options(JsonNode a) {
        AskOptions.Builder b = AskOptions.builder()
                .topK(a.get("top_k").asInt())
                .hybrid(a.get("hybrid").asBoolean())
                .temperature(a.get("temperature").isNull() ? null : Double.valueOf(a.get("temperature").asDouble()))
                .systemPrompt(text(a.get("system_prompt")))
                .maxTokens(a.get("max_tokens").isNull() ? null : Integer.valueOf(a.get("max_tokens").asInt()))
                .sessionId(text(a.get("session_id")))
                .metadataFilter(filter(a.get("metadata_filter")));
        if (a.has("response_format") && !a.get("response_format").isNull()) {
            b.responseFormat(a.get("response_format"));
        }
        if (a.has("query_rewrite") && !a.get("query_rewrite").isNull()) {
            String s = a.get("query_rewrite").asText();
            b.queryRewrite("contextual".equals(s) ? QueryRewrite.CONTEXTUAL
                    : "hyde".equals(s) ? QueryRewrite.HYDE : QueryRewrite.MULTI_QUERY);
        }
        if (a.has("multi_query_n")) {
            b.multiQueryN(a.get("multi_query_n").asInt());
        }
        return b.build();
    }

    private static ObjectNode askTree(AskResult a) {
        ObjectNode m = obj();
        m.put("answer", a.answer());
        m.set("sources", tree(a.sources()));
        ArrayNode cits = MAPPER.createArrayNode();
        for (Citation c : a.citations()) {
            ObjectNode o = obj();
            o.put("source_number", c.sourceNumber());
            o.put("document_name", c.documentName());
            o.put("document_id", c.documentId());
            o.put("chunk_id", c.chunkId());
            o.put("chunk_index", c.chunkIndex());
            o.put("text_preview", c.textPreview());
            cits.add(o);
        }
        m.set("citations", cits);
        putText(m, "provider_used", a.providerUsed());
        if (a.cost() != null) {
            putText(m, "model_used", a.modelUsed());
        }
        if (a.usage() == null) {
            m.putNull("usage");
        } else {
            ObjectNode u = obj();
            u.put("prompt_tokens", a.usage().promptTokens());
            u.put("completion_tokens", a.usage().completionTokens());
            u.put("total_tokens", a.usage().totalTokens());
            m.set("usage", u);
        }
        m.put("chunks_sent", a.chunksSent());
        if (a.structured() != null) {
            m.set("structured", a.structured());
        }
        if (a.structuredValid() != null) {
            m.put("structured_valid", a.structuredValid().booleanValue());
        }
        if (a.structuredEnforcement() != null) {
            m.put("structured_enforcement", a.structuredEnforcement());
        }
        if (a.queryRewrite() != null) {
            ObjectNode q = obj();
            q.put("strategy", a.queryRewrite().strategy());
            if ("contextual".equals(a.queryRewrite().strategy())) {
                q.put("rewritten_query", a.queryRewrite().rewrittenQuery());
            } else if ("hyde".equals(a.queryRewrite().strategy())) {
                q.put("hyde_document", a.queryRewrite().hydeDocument());
            } else {
                q.set("query_variants", tree(a.queryRewrite().queryVariants()));
            }
            m.set("query_rewrite", q);
        }
        if (a.cost() != null) {
            ObjectNode c = obj();
            putNum(c, "cost_usd", a.cost().costUsd());
            c.put("cumulative_cost_usd", a.cost().cumulativeCostUsd());
            c.put("pricing_available", a.cost().pricingAvailable());
            m.set("cost", c);
        }
        if (a.guardrailBlocked() != null) {
            m.put("guardrail_blocked", a.guardrailBlocked().booleanValue());
        }
        return m;
    }

    private static JsonNode run(RagLeap rag, String method, JsonNode a) throws Exception {
        switch (method) {
            case "ask":
                return askTree(rag.ask(a.get("query").asText(), options(a)));
            case "ask_stream": {
                List<String> pieces = new ArrayList<>();
                rag.askStream(a.get("query").asText(), options(a), pieces::add);
                return tree(pieces);
            }
            case "retrieve": {
                ArrayNode arr = MAPPER.createArrayNode();
                for (SearchResult c : rag.retrieve(a.get("query").asText(), a.get("top_k").asInt(),
                        a.get("hybrid").asBoolean(), filter(a.get("metadata_filter")))) {
                    ObjectNode o = obj();
                    o.put("chunk_id", c.chunkId());
                    o.put("text", c.text());
                    o.put("similarity_score", c.similarityScore());
                    o.put("document_id", c.documentId());
                    o.put("document_name", c.documentName());
                    o.put("chunk_index", c.chunkIndex());
                    o.put("retrieval_method", c.retrievalMethod());
                    arr.add(o);
                }
                return arr;
            }
            case "evaluate": {
                List<EvalCase> cases = new ArrayList<>();
                for (JsonNode c : a.get("test_cases")) {
                    cases.add(new EvalCase(c.get("query").asText(),
                            c.has("expected_document") ? c.get("expected_document").asText() : null,
                            c.has("expected_keywords") ? strings(c.get("expected_keywords")) : List.of()));
                }
                EvaluationResult r = rag.evaluate(cases, AskOptions.defaults());
                ObjectNode m = obj();
                putNum(m, "retrieval_hit_rate", r.retrievalHitRate());
                putNum(m, "keyword_coverage_rate", r.keywordCoverageRate());
                putNum(m, "groundedness_rate", r.groundednessRate());
                ArrayNode arr = MAPPER.createArrayNode();
                for (CaseResult c : r.results()) {
                    ObjectNode o = obj();
                    o.put("query", c.query());
                    putText(o, "answer", c.answer());
                    o.set("sources", tree(c.sources()));
                    if (c.retrievalHit() == null) {
                        o.putNull("retrieval_hit");
                    } else {
                        o.put("retrieval_hit", c.retrievalHit().booleanValue());
                    }
                    putNum(o, "keyword_coverage", c.keywordCoverage());
                    o.set("keywords_found", tree(c.keywordsFound()));
                    putNum(o, "groundedness", c.groundedness());
                    arr.add(o);
                }
                m.set("results", arr);
                return m;
            }
            default:
                throw new IllegalStateException("unknown method " + method);
        }
    }

    private static String abbreviate(String s) {
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }

    @Test
    void facadeMatchesPython() throws Exception {
        Path file = Path.of(System.getenv("RAGLEAP_FACADE_PARITY_DIR")).resolve("facade_cases.json");
        JsonNode cases = MAPPER.readTree(file.toFile());
        List<String> bad = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            JsonNode st = c.get("settings");
            List<String> log = new ArrayList<>();
            ProviderConfig fallback = provider("fallback-model");
            Set<String> fail = new HashSet<>(strings(st.get("embed_fail")));
            Function<String, List<Double>> embed = t -> {
                ObjectNode e = obj();
                e.put("c", "embed");
                e.put("text", t);
                log.add(canon(e));
                return fail.contains(t) ? null : List.of((double) t.length(), 1.0);
            };
            List<UnaryOperator<String>> guards = new ArrayList<>();
            for (String g : strings(st.get("output_guardrails"))) {
                guards.add(GUARDS.get(g));
            }
            List<Consumer<Map<String, Object>>> onQuery = List.of(ev -> log.add(hook("on_query", ev)));
            List<Consumer<Map<String, Object>>> onAnswer = List.of(ev -> log.add(hook("on_answer", ev)));
            RagLeap rag = new RagLeap(new RagLeap.Parts(null, "postgresql://unused", 2,
                    new FakeBackend(st.get("results"), log), embed, "model-1",
                    new FakeMemory(st.get("history").asText(), log),
                    new FakeGenerator(st.get("gen"), strings(st.get("stream_pieces")), log, fallback), null,
                    st.get("cache").asBoolean() ? new QueryEmbeddingCache(100) : null,
                    new CostTracker(null, st.get("budget").isNull() ? null : Double.valueOf(st.get("budget").asDouble())),
                    st.get("fallback").asBoolean() ? fallback : null, guards, onQuery, onAnswer));

            ArrayNode results = MAPPER.createArrayNode();
            String raised = null;
            try {
                for (int i = 0; i < st.get("repeat").asInt(); i++) {
                    results.add(run(rag, c.get("method").asText(), c.get("args")));
                }
            } catch (IllegalArgumentException e) {
                raised = e.getMessage();
            }
            JsonNode exp = c.get("expected");
            String expRaises = text(exp.get("raises"));
            if (expRaises != null || raised != null) {
                if (expRaises == null || !expRaises.equals(raised)) {
                    bad.add(name + ": raises java=" + raised + " python=" + expRaises);
                    continue;
                }
            } else {
                String got = canon(results);
                String want = canon(exp.get("results"));
                if (!got.equals(want)) {
                    bad.add(name + ": results differ\n  java:   " + abbreviate(got) + "\n  python: " + abbreviate(want));
                    continue;
                }
            }
            List<String> expLog = new ArrayList<>();
            for (JsonNode e : c.get("log")) {
                expLog.add(canon(e));
            }
            if (!expLog.equals(log)) {
                String detail = "";
                for (int i = 0; i < Math.max(expLog.size(), log.size()); i++) {
                    if (i >= expLog.size() || i >= log.size() || !expLog.get(i).equals(log.get(i))) {
                        detail = " first difference at log entry " + i
                                + "\n  java:   " + (i < log.size() ? abbreviate(log.get(i)) : "none")
                                + "\n  python: " + (i < expLog.size() ? abbreviate(expLog.get(i)) : "none");
                        break;
                    }
                }
                bad.add(name + ": logs differ (java " + log.size() + ", python " + expLog.size() + ")" + detail);
            }
        }
        assertTrue(bad.isEmpty(), cases.size() + " scenarios, " + bad.size() + " problems:\n" + String.join("\n", bad));
    }

    private static String hook(String name, Map<String, Object> event) {
        ObjectNode e = obj();
        e.put("c", "hook");
        e.put("name", name);
        e.set("event", tree(event));
        return canon(e);
    }
}
