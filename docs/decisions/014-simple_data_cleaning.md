# Decision 014: Simple Production Data Cleaning

**Date:** **2026**-08-12

## Context

The production database contains product and promotion data collected from retailer feeds. Although these feeds provide valuable information, they can also contain incomplete, suspicious, or unusable records.

Promotion items may reference products that do not exist in the database. These orphan promotion items are difficult to interpret in production because their product identities are unknown. They may still contain useful information, so removing them is not necessarily appropriate in every context.

The product catalog also contains suspicious records, including products with no name, zero prices, or appearances in only one store. More aggressive cleaning could remove additional questionable records, but it also increases the risk of deleting legitimate products.

## Decision

Production data cleaning will use conservative rules to remove records that are clearly unusable or sufficiently suspicious.

For promotion items, the production loading pipeline filters out entries with missing discounted prices or product codes that cannot be matched against known products. Product matching checks the global product catalog, store-specific products, and pharmacy product tables.

For global products, a separate cleanup process identifies suspicious records using criteria such as missing names, zero-price data, and limited appearances. Products classified as `delete` or `ultra_high` severity are eligible for deletion according to the cleanup rules.

These operations are part of production data maintenance. Development and testing environments initially retain the original, unfiltered promotion-loading behavior to support investigation and validation.

## Rationale

Orphan promotion items can be confusing in production because the application cannot reliably identify the products they refer to. Filtering these entries keeps the production promotion data more consistent with the products the application actually knows.

However, unknown promotion items may be useful for future investigation or product discovery. Their removal from the production loading flow should not be interpreted as proof that the source data is worthless.

Product cleanup follows the same principle but starts conservatively. Missing names, zero prices, and unusually limited store coverage can indicate unreliable records, yet none of these characteristics alone necessarily proves that a product is invalid.

The initial rules prioritize removing the most suspicious records while limiting the risk of deleting legitimate products. This approach has already resulted in approximately 5,000 product deletions, providing an initial improvement without attempting an exhaustive cleanup of the entire catalog.

## Future Changes

Cleaning rules can be expanded as more data-quality issues are identified and validated. Potential improvements include additional suspicious-product indicators, better handling of unknown promotion items, and improved separation of supermarket and pharmacy data.

Development and testing environments may eventually adopt the same cleaning rules, with the necessary separation to allow raw data and pharmacy-specific records to be investigated independently.

**Principle:** prioritize reliable production data through conservative, evidence-based cleaning; remove clearly unusable records while preserving the possibility of investigating uncertain data before applying more aggressive rules.