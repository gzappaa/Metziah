# Decision 009: Shared Downloader Architecture

**Date:** **2026**-09-12

## Context

The Metziah feed downloader originally implemented the four store-level feed types as separate modules:

```text downloaders/ ├── prices.py ├── promos.py ├── pricesfull.py └── promosfull.py ```

Each module contained its own implementation for the different publishing sources, including PublishedPrices, BinaProjects, Laibcatalog, **HTML** sources, Carrefour, Mishnat Yosef, and Wolt.

As development continued, substantial parts of the implementation were found to be duplicated between the modules.

In particular:

- `Price` and `Promo` follow the same download semantics.
- `PriceFull` and `PromoFull` follow the same download semantics.
- Source-specific listing, normalization, saving, and pagination behavior is shared across all feed types.
- The main difference between the modules is the feed type and the source-specific parameters required to retrieve it.

This made the four modules increasingly difficult to maintain independently.

## Decision

The downloader implementation was reorganized around shared functionality while keeping the individual feed-type modules as the public entry points.

The new structure is:

```text downloaders/ ├── common.py ├── delta_family.py ├── full_family.py ├── prices.py ├── promos.py ├── pricesfull.py ├── promosfull.py ├── stores.py └── runner.py ```

### Delta feed family

`Price` and `Promo` share the same semantics:

```text Price Promo ```

Their common behavior was moved into:

```text delta_family.py ```

This includes:

- finding matching files
- filtering files by date and feed type
- store-level storage paths
- saving delta files

The individual modules remain responsible for specifying their feed type and source-specific parameters.

### Full feed family

`PriceFull` and `PromoFull` share a different set of semantics.

Unlike delta feeds, only the latest file for each `(chain_id, store_id)` is retained for the current day.

Their shared behavior was therefore moved into:

```text full_family.py ```

This includes:

- finding the latest file per store
- extracting file timestamps
- test-mode limiting
- saving full files
- removing older same-day files after a successful replacement

`pricesfull.py` and `promosfull.py` continue to provide the feed-specific configuration.

### Common source functionality

Protocol-independent functionality used across the downloader modules was moved into:

```text common.py ```

This includes generic operations such as:

- data directory selection
- synchronous and asynchronous file saving
- test-mode handling
- PublishedPrices recursive listing
- Bina store filtering
- Carrefour listing normalization
- Wolt **URL** normalization
- Mishnat Yosef listing normalization
- **HTML** pagination and candidate discovery

This prevents each feed module from maintaining its own copy of the same infrastructure.

### Common runner

The seven publishing-source execution flow was also centralized in:

```text runner.py ```

The runner is responsible for executing the sources in the standard order:

```text PublishedPrices → BinaProjects → Laibcatalog → **HTML** sources → Carrefour → Mishnat Yosef → Wolt ```

The individual feed modules provide the functions needed for each source, while `runner.py` handles the common orchestration, **CLI** test mode, source registry, error handling, and final accumulation of downloaded files.

### Stores remains separate

`Stores` was not placed into either the delta or full feed family.

Stores feeds have different semantics because they represent chain-level store registries rather than store-level Price/Promo feeds.

Therefore:

```text stores.py ```

keeps its own Stores-specific selection and download logic while reusing the generic helpers from `common.py`.

## Result

The downloader now separates:

```text
What is being downloaded
        ↓
prices.py
promos.py
pricesfull.py
promosfull.py
stores.py
```

from:

```text
How common downloader operations work
        ↓
common.py
delta_family.py
full_family.py
runner.py
```

This removes duplicated logic while preserving the existing feed-specific modules and the same seven-source download flow.