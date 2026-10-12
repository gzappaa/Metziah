# Decision 015: Store Product Category Normalization

**Date:** **2026**-07-12

# Context

One of the main challenges in building a supermarket price-comparison application is identifying equivalent products across different retailers.

Packaged products with standard barcodes, such as Coca-Cola, can generally be matched across stores using their shared product identifiers.

Store-specific products are much harder to compare. Products prepared by a store, sold by weight, or assigned internal retailer codes may have different names and identifiers across chains. For example, one retailer might list chicken breast as `חזה עוף`, while another uses `עוף חזה טרי`, each with a different internal code.

These products cannot reliably be matched across retailers using barcodes alone. However, users still need to discover them through meaningful categories and subcategories.

# Decision

Store-specific products will be organized using a manually maintained category and subcategory vocabulary.

The reference file `data/reference/store_products.json` defines the vocabulary, while `data/reference/store_categories.json` provides the category structure used by the application.

Products are assigned to categories and subcategories by matching vocabulary terms against their names. For example, the category `קצבייה` and subcategory `חזה עוף` can include store products whose names contain both `חזה` and `עוף`, even when their internal codes differ between retailers.

The vocabulary will be expanded incrementally as additional product types and category gaps are identified.

# Rationale

A comprehensive product-identity resolution system for retailer-specific products would require considerably more complexity because names, codes, descriptions, and packaging can vary between stores.

A manually maintained vocabulary provides a simple, practical starting point. It allows users to browse store-specific products by category and subcategory without requiring every product to be matched to an identical product at another retailer.

This approach also makes coverage improvements incremental: new subcategories and vocabulary terms can be added without redesigning the database or implementing a sophisticated matching system.

The main limitation is that keyword matching can produce ambiguous results. For example, `בננה` may appear in many differently named store products. These cases can be addressed through better ranking and more precise vocabulary rules as needed.

## Future Changes

The category vocabulary can be expanded to improve category and subcategory coverage across retailers. In the future, an algorithm could analyze retailer websites and product catalogs to discover candidate categories and subcategories, reducing the need for manual inspection and vocabulary creation.

Product matching could also evolve into a similarity-ranking system that evaluates product names, units, weights, prices, and other available attributes to estimate whether products from different retailers represent the same item. This could support more reliable cross-retailer matching and help prioritize ambiguous results.
These improvements can be introduced incrementally as the current vocabulary-based approach reveals its limitations.

Principle: start with a maintainable, manually validated vocabulary, then progressively automate category discovery and product similarity ranking as the data and requirements mature.