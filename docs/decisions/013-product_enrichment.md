# Decision 013: Product Enrichment and Metadata Normalization

**Date:** **2026**-10-07

## Context

Supermarket websites provide additional product information beyond the basic product names and barcodes available in price feeds. This information can include ingredients, nutritional values, translations, brands, descriptions, and category hierarchies.

The scraped product data is parsed into JSONL files under `data/parsed/` before being loaded into the database.

Because multiple retailers may provide metadata for the same barcode, a strategy is needed to combine these sources without unnecessarily overwriting existing information.

## Decision

Product metadata will be loaded into the dedicated `product_enrichment` table, with nutritional information normalized separately into `product_nutrition`.

The retailer with the largest number of parsed product barcodes is selected manually as the primary source of truth using the `--source` argument. This source is processed first, and the remaining retailers are used as fallbacks.

The primary source establishes the initial metadata for each product. Fallback sources can introduce additional enrichment records and fill fields that are still empty, but they do not overwrite existing non-empty metadata.

Category paths are preserved as scraped, while canonical categories and subcategories are derived using `data/reference/categories.json`. Unmapped category paths remain without canonical category assignments.

## Rationale

Selecting the retailer with the broadest barcode coverage provides a practical starting point for enriching the product catalog. Other retailers help fill gaps when the primary source lacks information.

This approach is not intended to be a perfect reconciliation system. Retailers may provide conflicting or incomplete metadata, and a more sophisticated source-ranking strategy could improve accuracy. However, manually selecting a primary source and using fallbacks is straightforward, efficient, and sufficient for the current stage of the project.

Keeping enrichment and normalized nutritional data separate from the core product identity also allows additional metadata to be collected without changing the global product catalog structure.

## Future Changes

The source-selection strategy can be improved if more reliable methods become necessary, such as field-specific source priorities or explicit conflict resolution.

Category mappings can also be expanded as additional retailer category paths are discovered. Nutrition normalization can evolve as more nutritional formats and units are encountered.

**Principle:** use the broadest available retailer source as the initial metadata baseline, fill missing information from other retailers, and keep enrichment separate from core product identity.