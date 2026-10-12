package com.ragleap.rag;

/** Cost of one answer. costUsd is null when no price is known for the provider and model. */
public record CostInfo(Double costUsd, double cumulativeCostUsd, boolean pricingAvailable) {
}
