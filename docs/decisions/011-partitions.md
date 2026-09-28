# Decision 011: Chain-Specific Table Partitions

**Date:** **2026**-09-16

## Context

The `prices` and `promotion_items` tables are partitioned by `chain_id`.

I considered a few approaches for managing the chain partitions:

- Hardcode all partitions directly in the main schema.
- Dynamically create partitions from `chains.json` whenever the application runs.
- Generate/manage partitions automatically from the chain reference data.
- Keep the partitions in a separate migration and add new ones manually when necessary.

## Decision

Chain partitions will be maintained in a dedicated migration:

```text database/migrations/002_chain_partitions.sql ```

The migration contains one partition for each chain currently defined in the chain reference data.

The main schema will only define the partitioned parent tables. The individual chain partitions will not be included in `001_schema.sql`.

## Rationale

The chain list is expected to be **very stable**. Chains publishing prices under the current transparency requirements are unlikely to change frequently.

If a significant change does occur — for example:

- a major new supermarket chain starts publishing prices,
- a chain stops publishing,
- legislation changes which chains are required to publish,
- or the set of relevant chains otherwise changes,

the change will be noticeable through the existing feed/file monitoring and can be handled as a small manual database update.

Given this expected stability, dynamically managing partitions adds complexity without providing much practical benefit.

Keeping the partitions in a separate migration also avoids cluttering the main schema while keeping the database structure explicit and reproducible.

## Future Changes

When a new chain needs to be supported, add its partition to `002_chain_partitions.sql` and apply the migration/update to the relevant database.

The chain reference files remain the application-level source of truth:

```text data/reference/chains.json data/reference/chains_extra.json ```

The partition migration represents the corresponding **database structure** for the current set of chains.

**Principle:** keep the stable database structure explicit and simple; handle the occasional chain change manually rather than introducing automation for a rarely changing set.