# Pricing engine

The engine combines reviewed price evidence with explicit sale scenarios.
Model version: `pricing-scenarios-v1`.
The implementation uses USD cents for money.
The model is not a validated forecast of card prices or sale speed.

## Price evidence

The engine prefers a qualifying sold estimate over an active-listing scenario.
Sold evidence must pass the [sold-analysis checks](../server/analysis.py).
Active observations must pass the [listing-evidence checks](../server/pricing_engine.py).

Eligible active listings require an exact reviewed match and a current identity signature.
They must be active fixed-price listings in USD with known buyer shipping.
The observation must fall within the past 14 days.
Sold comparisons use a 90-day window.
Excluded records retain their exclusion reasons.

The engine deduplicates source listing identifiers.
A reviewer can supply `physical_copy_key` to identify observations of the same physical copy.
The field does not perform automatic image matching.

```text
delivered_ask = asking_price + buyer_shipping
asking_reference = median(delivered_ask)
listing_sale_scenario = asking_reference * listing_factor
```

The default `listing_factor` is `0.80`.
It is an assumption, not a measured negotiation discount.
Asking prices do not prove completed sales.
No qualifying evidence leaves the card unpriced.
Unknown values do not become zero values.
New evidence requires another review or import.

## Simulation assumptions

| Input | Default | Meaning |
| --- | ---: | --- |
| `listing_factor` | 0.80 | Fraction of the asking reference used in the scenario |
| `p30` | 0.35 | Assumed chance of sale within 30 days |
| `market_sigma` | 0.15 | Shared market price variation |
| `player_sigma` | 0.15 | Shared player price variation |
| `product_sigma` | 0.10 | Shared product price variation |
| `card_sigma` | 0.20 | Shared exact-variant price variation |

These defaults are uncalibrated assumptions.
The simulator combines normal shocks in a mean-preserving lognormal price multiplier:

```text
variance = market_sigma**2 + player_sigma**2 + product_sigma**2 + card_sigma**2
simulated_price = round(reference_price * exp(shared_shocks - variance / 2))
P(sold by T days) = 1 - (1 - p30) ** (T / 30)
```

Exact duplicate variants share a price draw and a median reference.
Physical copies remain separate inventory items.
An unpriced copy remains outside the model even when another copy has a price reference.
Individual sale events remain independent of each other and of price shocks.
The model does not infer sale dates or automatic appreciation.

The interface defaults to 10,000 trials and seed `42`.
More trials improve numerical stability, not the quality of the assumptions.

## Strategies and costs

| Strategy | Behavior |
| --- | --- |
| Individual sales | Each modeled card has its own sale event and shipment. |
| Bundles | Groups in stable card-ID order share one sale event and shipment. |
| Hold | No cards sell. The result retains purchase cost and modeled inventory value. |
| Scheduled reduction | Unsold cards enter a second period with separate price and sale-probability inputs. |

Review bundle membership before treating a group as a suitable real listing.
A lower price does not automatically increase the modeled sale probability.
Selling costs apply only when a simulated sale occurs.

The [shared cost engine](../server/analysis.py) applies editable postage, packaging, tax, percentage fees, and fixed fees.
Its built-in fee scenario does not establish the fees for your account.
Verify current fees and your shipping choice before a real listing.
Account discounts and promoted-listing charges require separate consideration.

## Results and saved runs

Results distinguish gross sales, net cash recovered, realized profit, retained purchase cost, and modeled unsold inventory value.
Unknown purchase costs remain outside profit calculations.
Retained inventory value is not cash.
The 10th, 50th, and 90th percentiles describe scenario results, not calibrated confidence intervals.

Loss probability includes only trials with at least one sold card whose purchase cost is known.
The result reports the denominator.
It returns no loss estimate when that denominator is zero.
No-sale probability describes modeled cards only.

Each saved run records its input report, effective options, costs, seed, fingerprints, model version, and result.
Later evidence does not alter a saved result.
Repeat a run with the same recorded inputs to check deterministic replay.

## New-release sandbox

The sandbox evaluates three explicit future price factors without adding cards to the collection.
The default factors are `0.60`, `0.85`, and `1.20` for low, base, and high paths.
Each path uses the same seed to isolate the selected price factor.
The paths have no assigned probabilities.
Release age supplies context without an automatic price adjustment.

Historical release cohorts, supply growth, launch-premium fitting, and sealed-product expected value are not implemented.
The sandbox remains an unvalidated scenario tool.

## Implementation and verification

- [Pricing model](../server/pricing_engine.py)
- [Pricing API](../server/pricing_api.py)
- [Selling cost calculations](../server/analysis.py)
- [Engine interface](../src/PricingEngine.jsx)
- [Model tests](../tests/test_pricing_engine.py)
- [API tests](../tests/test_pricing_api.py)

Tests cover accounting behavior, evidence exclusions, deterministic replay, and supported input limits with synthetic records.
Passing software tests does not establish forecast accuracy.
Predictive accuracy, real sale probabilities, and future release paths remain unvalidated.
