# Decision 008: Store Identity, Subchain Handling, and Duplicate Feed Monitoring

**Date:** **2026**-09-11

## Context

During development of the Metziah feed pipeline, a case was identified where the same `chain_id` and `store_id` appeared in published filenames with different `sub_chain_id` values.

The initial question was whether the storage and database model should use:

```text chain_id / store_id ````

or:

```text chain_id / sub_chain_id / store_id ```

The issue is important because `sub_chain_id` is present in many published filenames, but it is not consistently useful as part of the store identity.

Most stores observed in the available feeds use the store ID as the unique identifier within a chain. At the same time, some feeds contain a subchain ID while others do not, and there are already more than **150** stores where no meaningful subchain distinction is needed.

The observed data therefore does not support treating:

```text chain_id + sub_chain_id + store_id ```

as the universal store identity.

For example, a filename can look like:

```text PriceFull729000000001-**000**-**001**-... ```

where `**000**` is a real subchain value, while other stores or sources may not provide a subchain distinction that needs to affect the Metziah store identity.

## Problem Identified

The specific duplicate case discovered in the Super Sapir BinaProjects feed was:

```text chain_id:     **7290058156016** store_id:     **396** sub_chain_id: **000** ```

and:

```text chain_id:     **7290058156016** store_id:     **396** sub_chain_id: **017** ```

The `**000**-**396**` feed contains the normal files for the store.

The `**017**-**396**` feed was observed publishing only a `PromoFull` file containing an empty promotions collection. The **XML** itself also reported:

```xml <SubChainID>**000**</SubChainID> ```

despite the filename containing `**017**`.

This indicates that `**017**-**396**` is not currently a meaningful second store identity. It is treated as an erroneous/duplicate feed rather than as a separate store.

Another duplicate store case was also observed for store `**502**`. This case does not currently show evidence of the same type of chain/subchain conflict.

Overall, among more than **2300** stores observed in the current store data, only a very small number of duplicate cases were found. Approximately 99.99% of the observed stores can be represented correctly using:

```text (chain_id, store_id) ```

## Options Considered

### Option 1: Make `chain_id + sub_chain_id + store_id` the universal identity

The entire system could be changed to use:

```text chain_id / sub_chain_id / store_id ```

for file storage and database relationships.

This would make every subchain explicitly represented in the filesystem and could prevent two feeds with different subchains from being written to the same directory.

However, this would also introduce unnecessary complexity throughout the system.

At least **150**+ currently observed stores do not require a meaningful subchain distinction. A value such as:

```text **000** ```

could be assigned to stores without a subchain, but this would turn an absent concept into an artificial value throughout the system.

It would also require changes to the database model and all related foreign keys and unique constraints.

Instead of:

```text (chain_id, store_id) ```

the database would need to consistently use something equivalent to:

```text (chain_id, sub_chain_id, store_id) ```

This would affect the store registry and every table referencing stores.

More importantly, changing the filesystem structure would not eliminate the underlying data-quality problem.

For example, if both:

```text PriceFull...-**000**-**396** PriceFull...-**017**-**396** ```

were stored separately, the database would still need to determine whether these represent:

- two legitimate stores,
- two subchains of the same store,
- or an erroneous duplicate feed.

If the database continues to use `(chain_id, store_id)` as its identity, both files would still eventually refer to the same database store.

Therefore, adding `sub_chain_id` to the filesystem does not remove the need for monitoring.

### Option 2: Keep `chain_id + store_id` as the identity and monitor subchains

The alternative is to keep the simpler and already well-supported model:

```text chain_id / store_id ```

and treat `sub_chain_id` as feed metadata rather than as part of the store identity.

The existing monitoring system can detect cases where the same:

```text (chain_id, store_id) ```

appears with multiple subchains.

This preserves the simple structure for the overwhelming majority of stores while still making unexpected publisher behavior visible.

## Decision

Metziah will continue to use:

```text (chain_id, store_id) ```

as the canonical store identity.

The filesystem will therefore continue to use:

```text data/feeds/{chain_id}/{store_id}/ ```

rather than:

```text data/feeds/{chain_id}/{sub_chain_id}/{store_id}/ ```

`sub_chain_id` remains part of the published filename and file metadata, but does not become part of the canonical store key.

This decision follows the observed data: the store ID is effectively unique within a chain for the vast majority of feeds, while subchains are not consistently required to distinguish stores.

## Monitoring Requirement

Keeping the simpler identity does **not** mean that subchain conflicts can be ignored.

The monitoring system must continue checking for multiple subchains appearing for the same:

```text (chain_id, store_id) ```

This is implemented by:

```text monitoring/check_store_duplicates.py ```

The purpose of this monitoring is not primarily to protect the filesystem. It is to detect publisher/data-quality anomalies that could otherwise cause multiple feeds to be interpreted as the same store.

For example, a future publisher could potentially begin publishing:

```text PriceFull...-**001**-**001** PromoFull...-**002**-**001** ```

for the same `(chain_id, store_id)`.

Even if those files were stored in separate subchain directories, the database layer would still have to decide how those files relate to the same store.

Therefore, subchain monitoring remains necessary regardless of whether the filesystem contains a subchain directory.

## Known Exception

The currently identified invalid BinaProjects feed is:

```text chain_id:     **7290058156016** sub_chain_id: **017** store_id:     **396** ```

This feed is explicitly ignored by the BinaProjects downloader.

The valid observed feed for the store is:

```text chain_id:     **7290058156016** sub_chain_id: **000** store_id:     **396** ```

The exclusion is intentionally specific to this known bad publisher/feed combination. It does not globally ignore subchain `**017**`, and it does not change the canonical store identity.

## Why This Decision Is Preferred

The chosen design separates two different concepts:

**Store identity:**

```text (chain_id, store_id) ```

**Publisher/feed metadata:**

```text sub_chain_id ```

This keeps the core database and filesystem model simple while still preserving the information necessary to detect abnormal publisher behavior.

If future evidence shows that subchains represent genuine, persistent store identities rather than publisher/feed metadata, the model can be revisited.

Until then, introducing `sub_chain_id` into every store relationship would add complexity to the entire system to solve a problem currently observed in only a tiny fraction of stores.

The monitoring system provides the necessary safety mechanism without making the normal case more complicated.

```

I think the **most important conceptual sentence** in this decision is:

> **Changing the filesystem to include `sub_chain_id` would solve a storage collision, but it would not solve the identity/data-quality problem.**

That's really the reason your current architecture makes more sense. If `**017**-**396**` becomes a real feed tomorrow, the monitor catches it and you investigate whether it's a legitimate new store/subchain or garbage. You don't need to redesign the entire database today to protect against a hypothetical publisher behavior. ```