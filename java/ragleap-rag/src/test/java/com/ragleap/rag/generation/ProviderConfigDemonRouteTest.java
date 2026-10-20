package com.ragleap.rag.generation;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** DemonRoute was added to the Python provider table; Java keeps the same table. */
class ProviderConfigDemonRouteTest {

    @Test
    void demonrouteHasItsDefaultBaseUrl() {
        ProviderConfig config = new ProviderConfig("demonroute", "example-key", "example-model", null);
        assertEquals("https://api.demonroute.com/v1", config.getBaseUrl());
        assertEquals("https://api.demonroute.com/v1", ProviderConfig.PROVIDER_BASE_URLS.get("demonroute"));
    }
}
