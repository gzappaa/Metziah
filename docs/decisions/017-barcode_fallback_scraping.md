# Decision 017: Recover Missing Product Barcodes from **GS1** Image URLs

# Date: 2026-10-28 

# Context 

Product barcodes are important identifiers in the Metziah product catalog. They help identify equivalent products across retailers and support reliable product matching.

However, some raw retailer product records have a missing barcode even when the product's image **URL** contains a barcode as part of its path. For example:

[https://example.com/gs1-products/**1540**/{{size}}/**7290002133506**-**983383**/**7290002133506**/image.jpg](https://example.com/gs1-products/**1540**/{{size}}/**7290002133506**-**983383**/**7290002133506**/image.jpg)

In this case, the **URL** contains the candidate barcode **7290002133506**, despite the source record having no barcode value.

Leaving these barcodes unrecovered results in avoidable gaps in the parsed product catalog. Conversely, extracting arbitrary digit sequences from image URLs could introduce invalid identifiers or incorrectly interpret unrelated numbers as barcodes. Decision When a product's source barcode is missing, the parser will attempt to recover it from the product's image URLs.

The fallback follows these rules: ## Preserve any non-empty barcode provided by the source data. ## Only inspect URLs belonging to the gs1-products path. ## Ignore URLs containing product-images. ## Extract the digit sequence immediately following the {{size}}/ segment. ## Validate the extracted candidate using the existing is_valid_gtin() function. ## If a valid candidate is found, use it as the product barcode. Otherwise, leave the barcode as null. The parser will inspect available image URLs until it finds the first valid candidate. The original image URLs remain unchanged in the parsed output.

The product schema does not change: recovered barcodes are stored in the existing barcode field. Rationale This approach recovers identifiers already present in the source data without introducing additional network requests, external dependencies, or a separate barcode lookup process.

Restricting extraction to the expected **URL** structure reduces the risk of interpreting unrelated numeric values as product identifiers. **GTIN** validation provides an additional safeguard by checking the candidate's supported length and check digit.

Preserving existing source barcodes also avoids unexpectedly overriding retailer-provided values. The fallback is used only when the source barcode is missing.

Finally, recovery counts are logged per retailer during parsed **JSONL** generation. These metrics make it possible to measure how many barcodes the fallback recovers for each retailer and assess whether the approach is providing meaningful coverage improvements.
Limitations
- A barcode embedded in an image **URL** is not guaranteed to represent the correct product identifier, even if it passes **GTIN** validation.
- Recovery depends on the **URL** following the expected gs1-products structure.
- Products without suitable image URLs, or without a valid candidate in those URLs, remain without a barcode.
- The current implementation selects the first valid candidate rather than comparing candidates across images.
These limitations mean recovered barcodes should be understood as inferred identifiers, not independently verified product identities.

### Future Changes

Recovery metrics can be used to evaluate the fallback across retailers and identify where additional investigation is worthwhile.

Future improvements could include tracking whether a barcode was sourced directly or inferred, comparing candidates across multiple images, and validating inferred identifiers against other product attributes or trusted barcode datasets.

Principle: preserve source identifiers, recover missing values only from known structured sources, validate every candidate, and measure the impact of fallback logic through logging.