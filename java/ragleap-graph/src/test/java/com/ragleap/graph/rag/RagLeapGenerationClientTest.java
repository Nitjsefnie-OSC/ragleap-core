package com.ragleap.graph.rag;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ragleap.graph.ExtractedEntity;
import com.ragleap.graph.ExtractedRelation;
import com.ragleap.graph.ExtractionConfig;
import com.ragleap.graph.ExtractionException;
import com.ragleap.graph.LlmEntityExtractor;
import com.ragleap.graph.LlmRelationExtractor;
import com.ragleap.graph.LlmResult;
import com.ragleap.rag.generation.ProviderConfig;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Runs the real ragleap-rag GenerationService against a local fake OpenAI-style server. No real provider is called;
 * the model's answer is scripted.
 */
class RagLeapGenerationClientTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private HttpServer server;
    private final List<String> paths = new ArrayList<>();
    private final List<String> bodies = new ArrayList<>();
    private volatile int status = 200;
    private volatile String content = "{}";

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            paths.add(exchange.getRequestURI().getPath());
            bodies.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            ObjectNode message = MAPPER.createObjectNode().put("role", "assistant").put("content", content);
            ObjectNode choice = MAPPER.createObjectNode().put("index", 0).put("finish_reason", "stop");
            choice.set("message", message);
            ObjectNode usage = MAPPER.createObjectNode().put("prompt_tokens", 5).put("completion_tokens", 7)
                    .put("total_tokens", 12);
            ObjectNode root = MAPPER.createObjectNode();
            root.putArray("choices").add(choice);
            root.set("usage", usage);
            byte[] bytes = (status == 200 ? root.toString() : "{\"error\":\"scripted failure\"}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private ProviderConfig provider() {
        return new ProviderConfig("openai", "test-key", "test-model",
                "http://127.0.0.1:" + server.getAddress().getPort() + "/v1");
    }

    private static void texts(JsonNode n, StringBuilder sb) {
        if (n.isTextual()) {
            sb.append(n.asText()).append('\n');
        } else {
            n.forEach(c -> texts(c, sb));
        }
    }

    private ExtractionConfig config() {
        return ExtractionConfig.builder().method(ExtractionConfig.Method.LLM)
                .llm(RagLeapGenerationClient.of(provider())).extractRelations(true).build();
    }

    @Test
    void resultFieldsAreMappedAndStructuredOutputIsValidated() throws Exception {
        content = "{\"entities\":[{\"name\":\"Acme\",\"type\":\"ORG\"}]}";
        JsonNode schema = MAPPER.readTree("{\"type\":\"object\",\"properties\":{\"entities\":{\"type\":\"array\"}},"
                + "\"required\":[\"entities\"]}");
        LlmResult r = RagLeapGenerationClient.of(provider()).generate("SYS", "Q?", "some text", "doc", schema, 0.0);
        assertEquals("openai", r.providerUsed());
        assertEquals(content, r.answer());
        assertEquals(Boolean.TRUE, r.structuredValid());
        assertNotNull(r.structured());
        assertTrue(r.structured().has("entities"));
        assertNotNull(r.structuredEnforcement());
    }

    @Test
    void entityExtractionSendsTheExactPromptAndSchema() throws Exception {
        content = "{\"entities\":[{\"name\":\"Acme Corp\",\"type\":\"ORG\"},{\"name\":\"Alice\",\"type\":\"PERSON\"}]}";
        List<ExtractedEntity> out = new LlmEntityExtractor(config()).extract("Acme Corp hired Alice.", List.of("Widget"));
        assertEquals(List.of(new ExtractedEntity("Acme Corp", "ORG"), new ExtractedEntity("Alice", "PERSON")), out);

        assertEquals(1, bodies.size());
        assertTrue(paths.get(0).startsWith("/v1"), paths.get(0));
        JsonNode req = MAPPER.readTree(bodies.get(0));
        assertEquals(0.0, req.path("temperature").asDouble(-1.0), 0.0);
        StringBuilder sb = new StringBuilder();
        texts(req, sb);
        String all = sb.toString();
        assertTrue(all.contains("You extract named entities from text."), all);
        assertTrue(all.contains("Context:"));
        assertTrue(all.contains("Acme Corp hired Alice."));
        assertTrue(all.contains("Question: Extract all named entities from the given text. Pay particular attention "
                + "to these known domain terms if present: Widget."), all);
        assertTrue(bodies.get(0).contains("\"entities\""), "the response schema must reach the provider");
    }

    @Test
    void relationExtractionWorksEndToEnd() {
        content = "{\"relations\":[{\"subject\":\"Alice\",\"relation_type\":\"works_at\",\"object\":\"Acme\"}]}";
        List<ExtractedRelation> out = new LlmRelationExtractor(config()).extract("Alice works at Acme.",
                List.of("Alice", "Acme"));
        assertEquals(List.of(new ExtractedRelation("Alice", "WORKS_AT", "Acme")), out);
    }

    @Test
    void providerFailureBecomesTheSameExtractionError() {
        status = 500;
        ExtractionException e = assertThrows(ExtractionException.class,
                () -> new LlmEntityExtractor(config()).extract("Acme Corp hired Alice."));
        assertEquals("RuntimeError", e.pythonType());
        assertTrue(e.getMessage().startsWith("LLM entity extraction failed on all configured providers: "),
                e.getMessage());
    }

    @Test
    void nullArgumentsAreRejected() {
        assertThrows(NullPointerException.class, () -> new RagLeapGenerationClient(null));
        assertThrows(NullPointerException.class, () -> RagLeapGenerationClient.of(null));
    }
}
