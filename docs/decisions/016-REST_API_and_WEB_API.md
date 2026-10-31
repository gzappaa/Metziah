# Decision 016: Separate REST API and Web Interface

**Date:** **2026**-10-12

# Context

Metziah collects and processes Israeli supermarket data, including product catalogs, prices, promotions, store information, and additional product metadata obtained through retailer website scraping and parsing.

The project maintains a global barcode catalog of approximately 200,000 products. Around 19,009 products have enriched metadata, including additional names, brands, categories, descriptions, ingredients, and nutritional information.

Although enrichment covers only a fraction of the catalog, these products account for 56.79% of production barcode product-store price listings, representing 7,270,231 out of 12,801,090 listings. This demonstrates that enrichment adds substantial value without being a prerequisite for maintaining a complete product catalog.

The project also benefits from exposing its data through a working API and a web interface. These provide a way to explore current supermarket data, demonstrate the project in a portfolio, and potentially support future applications and data analysis.

However, Metziah's primary objective is not to build a feature-rich API or a sophisticated frontend. The main focus is maintaining an accurate and reliable dataset, keeping ingestion pipelines operational, cleaning and normalizing retailer data, and making the resulting information useful for future analysis and open-source contributions.

# Decision

Maintain separate Web API and REST API interfaces with distinct responsibilities.

- Web API: serves HTML pages and HTMX interactions for the shopper-facing website, presenting product information, price comparisons, promotions, and enriched metadata when available.
- REST API: exposes structured JSON data through versioned endpoints under `/api/v1/`, supporting programmatic access to the supermarket dataset.

The REST API provides access to the product catalog independently of enrichment availability. Enrichment remains optional metadata rather than a requirement for product inclusion.

Keep the API intentionally simple at its current stage. Implement the functionality needed to expose and explore the dataset without attempting to build a comprehensive application platform or implementing every possible feature.

# Rationale

Separating the interfaces allows the website to provide a user-friendly experience while keeping the underlying data accessible in a structured format for other consumers.

Exposing the complete catalog is important because many valid products will not have enriched metadata. Restricting access to enriched products would unnecessarily exclude products that are present in supermarket price feeds.

The existing enrichment coverage of 56.79% of production barcode product-store listings demonstrates that a relatively small enriched catalog can already support a substantial portion of the available product data.

A working API and web interface also provide practical ways to visualize the dataset, demonstrate the project in a portfolio, and make the data more accessible for future use.

Nevertheless, development effort should remain proportional to the API's role in the project. Although the database already contains geographic coordinates for approximately 90% of stores and supports PostGIS, advanced capabilities such as geographic search and proximity-based queries are not current priorities.

The primary engineering effort should remain focused on data acquisition, pipeline reliability, data quality, normalization, and maintaining an accurate representation of supermarket prices and products. These capabilities form the foundation for future analytical work and potential open-source contributions, including enriching product data in other projects.

# Future Changes

The API can be extended when a concrete use case justifies the additional complexity. Potential improvements include geographic queries using existing PostGIS capabilities, additional filtering and comparison features, and new endpoints for analytical access.

Further development should prioritize features that materially improve data accessibility or demonstrate meaningful value without diverting excessive effort from the ingestion and data-quality pipeline.

Future analytical work may also use the collected dataset to investigate supermarket pricing and product availability or contribute useful product data to open-source projects.

**Principle:** prioritize the accuracy, completeness, and reliability of the supermarket dataset; maintain a simple working API and web interface to expose and demonstrate that data, and introduce additional features only when they provide clear value.