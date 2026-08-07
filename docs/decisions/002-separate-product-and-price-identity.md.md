# Decision 002: Separate product identity from store-specific prices

Date: 2026-08-07

## Context

The supermarket XML feeds provide item metadata and prices together inside
the same `<Item>` element.

Example:

```xml
<Item>
    <ItemCode>7290003026234</ItemCode>
    <ItemName>...</ItemName>
    <ItemPrice>30.9</ItemPrice>
    <StoreID>001</StoreID>
</Item>
```

Initially, a single table containing all XML fields was considered.

However, the feed represents two different concepts:
- Product identity (what the item is)
- Store pricing (how much a specific store sells it for)

The database needs to support:
- Comparing prices of the same product across supermarkets
- Storing different prices for different stores
- Avoiding unnecessary duplication of product metadata

There is also a third concept the feeds don't make explicit: not every
`ItemCode` is a real, globally-unique barcode. Loose/weighed items
(produce, deli, bakery) are often assigned short internal codes by each
retailer's own catalog system, which are **not** guaranteed unique across
chains -- two unrelated chains can use the same internal code for two
different products.

---

## Experiment

The `ItemCode` and `ItemType` fields were analyzed using Mahsanei Hashuk
price feeds, to check whether `ItemType` reliably predicts a real barcode.

Results:
- Total items analyzed: 702,014
- ItemType 1 items: 587,864
- ItemType 0 items: 114,150

Test performed:

```text
For every Item:
    if ItemType = 1:
        verify ItemCode length = 13
```

Result:

```text
ItemType 1 checked: 587,864
Violations: 0
```

This confirms that, in this chain, `ItemType = 1` items always carry a
13-digit `ItemCode` -- consistent with a real barcode (EAN-13).

**This experiment validates the assumption; it is not what the code
checks at ingestion time.** The actual detection rule used in
`storage/records.py::looks_like_barcode()` only inspects the shape of
`ItemCode` itself:

```python
_BARCODE_RE = re.compile(r"^\d{13}$")
```

`ItemType` is not read by the detection logic. It was used here purely
to sanity-check that a length-only rule wouldn't misclassify anything in
this chain's real data. This distinction matters because a future reader
could otherwise assume `ItemType` is load-bearing in the ingestion path,
when it currently isn't.

This behavior should not be assumed for every supermarket chain. Different
chains may expose different barcode formats (EAN-8, UPC-A, EAN-13,
GTIN-14) or may not set `ItemType` consistently at all. Barcode
identification remains a chain-specific ingestion decision, and the regex
above is scoped to what's been verified for Mahsanei Hashuk specifically.

---

## Decision

Use three tables instead of one merged table: two for product identity,
split by whether `item_code` is a real barcode, and one for store prices.

### products
Real barcodes only (`item_code` matches `^\d{13}$`). One row per barcode,
globally unique, shared across every chain that sells it.

```text
products
---------
item_code   (PK)
name
manufacturer
manufacturer_country
item_type
```

### store_products
Non-barcode / internal item_codes. Since these are assigned per retailer
and are not globally unique, this table is scoped to `(chain_id,
item_code)` rather than `item_code` alone.

```text
store_products
---------------
chain_id    (PK, part 1)
item_code   (PK, part 2)
name
manufacturer
manufacturer_country
item_type
```

This scoping carries an assumption: that a given chain assigns the same
internal `item_code` to the same product at every branch, not a different
product per store. That assumption is empirically checkable with
`scripts/check_item_code_consistency.py` against real downloaded feeds. If
it turns out false for some chain, `store_products` isn't a safe model for
that chain's non-barcode items -- their name/manufacturer/item_type would
need to live directly on `prices` instead, since there'd be no shared
identity above the (store, item) level to normalize into its own table.

### prices
Stores the relationship between a store and a product -- either kind.
`item_code` here has no foreign key, since it may point at a row in
`products` or a row in `store_products` depending on which kind it is,
and a single FK column can't reference two tables. Consistency is
enforced by the loader, not by Postgres.

```text
prices
---------
chain_id
store_id
item_code
price
unit_price
quantity
unit_qty
unit_measure
weighted
package_quantity
allow_discount
...
```

Note `chain_id` is part of the key here, not just `store_id` -- a raw
`StoreID` like `"001"` is only unique *within* a chain, not globally.

Each store has its own price record for the same product, and
`unit_qty`/`unit_measure`/`weighted`/`package_quantity` live here rather
than on the identity tables, since the same `item_code` can legitimately
be sold prepackaged at one branch and loose by weight at another --
that's "how it's sold here," not "what it is."

---

## Reason

A single combined table would duplicate product metadata:

```text
store   item_code        name          price
----------------------------------------------
001     7290003026234    Product A     5.90
002     7290003026234    Product A     6.20
003     7290003026234    Product A     5.50
```

The product information is repeated even though the product identity is
the same. Separating the tables models the real relationship -- but as
two identity trees, not one, since barcode and non-barcode items have
different sharing scopes:

```text
     Barcode Product                    Chain-Internal Product
   (global, in products)              (per-chain, in store_products)
            |                                      |
   -----------------------              -----------------------
   |          |          |              |          |
Store A    Store B    Store C        Store A    Store B    Store C
 price      price      price          price      price      price
(in prices)                          (in prices)
```

---

## Consequences

### Positive
- Easier cross-supermarket price comparison for real barcodes
- Less duplicated product metadata
- Product information updates happen once
- Price table contains only store-specific information
- Scales better as more supermarket chains are added
- Non-barcode items (produce, deli) don't pollute the global `products`
  identity space with codes that collide across chains

### Negative
- Barcode detection cannot rely on one universal rule across chains
- Each chain may require custom feed interpretation
- `store_products` relies on an unverified-per-chain assumption (same
  internal code = same product at every branch of that chain)
- `prices.item_code` has no FK, so referential integrity between a price
  row and its identity row is an application-level guarantee, not a
  database-level one
- Some ItemCodes may represent non-product entries

---

## Future considerations
- Validate barcode values using EAN/GTIN checksum algorithms, not just length
- Consider using `ItemType` (1 = barcode, 0 = everything else) as the
  barcode-detection signal instead of `ItemCode` length once verified
  across other chains -- confirmed reliable for Mahsanei Hashuk (0
  violations against 587,864 ItemType=1 items), but not yet adopted since
  other chains may not set ItemType the same way
- Add chain-specific barcode detection rules as more chains are onboarded
