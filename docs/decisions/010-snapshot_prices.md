# Decision 010: Handling Snapshot-Like `Price` Feeds

**Date:** **2026**-09-13

## Context

During the inspection of `Price` and `PriceFull` feeds, it was found that some publishers do not appear to provide a meaningful delta-style `Price` feed.

In particular, investigation of Laibcatalog-published chains showed that:

- `**7290455000004**` H. Cohen
- `**7290696200003**` Victory
- `**7290661400001**` Machsanei Hashuk


have `Price` files that behave as snapshots rather than true deltas.

This behavior is consistent with the behavior already observed for Machsanei Hashuk over an extended period of time. For these chains, `Price` and `PriceFull` are generally very similar in size and content, with the differences between them appearing predictable and already handled by the existing reconciliation logic.

The existing `Price`/`PriceFull` inspection also showed that the remaining suspicious cases cannot safely be assumed to follow the same behavior.

Therefore, treating every suspicious `Price` file as a valid delta would introduce unnecessary risk: a file that is actually a snapshot could be interpreted as an incremental update, potentially causing incorrect or stale product prices.

## Decision

For publishers and chains confirmed to publish snapshot-like `Price` feeds, `Price` will be treated as a snapshot and will not be relied upon as a delta feed.

The confirmed snapshot-like chains are:

```text
- `**7290455000004**` H. Cohen
- `**7290696200003**` Victory
- `**7290661400001**` Machsanei Hashuk
```

For the remaining stores that cannot currently be classified with confidence, the safer behavior is to **ignore `Price` and load only `PriceFull`**.

As of ****2026**-09-13**, this affects only approximately **11 stores out of ~2,**500** stores**.

This means that these stores may not receive intraday updates from `Price`, but their `PriceFull` feed remains the authoritative source for the store.

## Rationale

The decision prioritizes correctness over update frequency.

The cost of ignoring a potentially useful delta feed for 11 stores is limited: those stores may have slightly less frequent price updates during the day.

The cost of incorrectly treating a snapshot as a delta is potentially much larger, because it can result in an incorrect interpretation of the feed and consequently incorrect database state.

Since:

- `PriceFull` is available for these stores,
- the number of uncertain stores is very small,
- the behavior can be revisited as more historical data is collected,
- and the confirmed snapshot-like publishers already demonstrate that `Price` and `PriceFull` can be nearly identical,

using `PriceFull` as the conservative fallback is considered the safest current behavior.

## Reconciliation

The existing `Price`/`PriceFull` reconciliation logic remains in place.

Differences between `Price` and `PriceFull` for snapshot-like publishers are considered expected behavior when they follow the already observed and predictable patterns.

The decision does **not** imply that `Price` should be discarded globally. `Price` will continue to be processed for publishers/stores where its behavior has not been identified as snapshot-like.

## Future Review

This decision is intentionally conservative and can be revisited when additional evidence becomes available.

In particular, the currently uncertain stores should be monitored over multiple days to determine whether their `Price` feeds behave as genuine deltas or snapshots.

If their behavior becomes sufficiently clear, they can be moved into the appropriate category without changing the overall downloader architecture.

**Principle:** when the semantics of a `Price` feed are uncertain, prefer missing some intraday updates over risking incorrect price state.