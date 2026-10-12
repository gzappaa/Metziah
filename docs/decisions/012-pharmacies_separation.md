# Decision 012: Pharmacy Product Separation

**Date:** **2026**-10-06

## Context

Pharmacies are included in Israel's price-transparency system, even though they are not supermarkets, because they also sell products commonly found in supermarkets.
Pharmacy feeds contain approximately 20,000 unique pharmacy-specific products. Mixing these products into the normal supermarket catalog would unnecessarily increase its size with products belonging to a different retail domain.
In the future, supermarket and pharmacy products will need to be analyzed separately, including their prices, promotions, and product coverage.

## Decision

Pharmacy-specific products will be stored separately from the normal supermarket catalog.
Known barcodes that already exist in the global products table will continue to use the existing product record. Unknown pharmacy-only barcodes will be stored in pharmacy_products, while non-barcode and internal pharmacy items will be stored in pharmacy_store_products.
Pharmacy prices and promotions will not be fully separated yet. Their dedicated handling will be implemented in a future stage.

## Rationale

Maintaining separate pharmacy product tables prevents pharmacy-only products from unnecessarily expanding the supermarket catalog while preserving the ability to track products that appear across both retail domains.
Reusing existing global product records for known barcodes avoids unnecessary duplication when the same product is sold by both supermarkets and pharmacies.
This structure also establishes a foundation for future analyses comparing supermarket and pharmacy products independently, without requiring a complete redesign of the product catalog.
Implementing the separation incrementally allows pharmacy ingestion to be supported now while leaving the remaining price and promotion separation for later.

## Future Changes

Pharmacy prices and promotions will eventually be separated from the normal supermarket data flows so that both retail domains can be analyzed independently.
Development and testing environments may also adopt the production data-cleaning rules and the complete pharmacy separation.

**Principle:** keep pharmacy-specific products separate from the supermarket catalog while reusing shared product identities; extend the separation to prices and promotions when the dedicated pharmacy data flows are implemented.