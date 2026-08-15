# Decision 004: File tracking for feed monitoring and dependencies

**Date:** 2026-08-15

## Context

The Laibcatalog API removes feed files after roughly 24 hours, so files available from the API cannot be relied on as a permanent record.

For Machsenei Hashuk, the feeds behave as follows:

- `PriceFull` — price snapshot.
- `Price` — also a price snapshot.
- `PromoFull` — promotion snapshot.
- `Promo` — incremental promotion updates.

When adding `Promo`, we needed a way to verify that the corresponding `PromoFull` snapshot had already been obtained/loaded before processing the incremental `Promo` files.

A simpler solution could have been to check whether the relevant files exist on disk or maintain separate flags. However, as more feed types and processing requirements are added, a centralized record of file state becomes more useful.

## Decision

Add a `file_tracking` table to monitor every feed file and its processing state.

The table tracks information such as:

```text
file_type
filename
downloaded
loaded
```

This allows the pipeline to determine:

- Which files were found.
- Which files were downloaded.
- Which files were loaded into the database.
- Whether the required `PromoFull` snapshot has been loaded before processing `Promo`.
- Which files are still pending processing.

## Reason

The immediate reason for introducing file tracking was the dependency between `PromoFull` and `Promo`.

However, keeping this state in a dedicated database table is more useful long-term than implementing separate checks for each feed type.

It also gives us a persistent record of files even after the upstream API removes them.

## Consequences

**Positive**

- Provides persistent ingestion state.
- Allows `Promo` → `PromoFull` dependencies to be enforced.
- Makes downloaded-but-not-loaded files easy to identify.
- Works for all current and future feed types.
- Does not depend on files still being present in the upstream API.

**Negative**

- Adds database bookkeeping.
- The tracking state must remain synchronized with actual download/load operations.

## Future considerations

The table can be extended with additional processing state or metadata as the ingestion pipeline grows.