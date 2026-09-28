# Decision 006: Filename Chain Monitoring and Store Chain-ID Enrichment

**Date:** **2026**-09-10

## Context

During development of the Metziah publisher discovery and store registry, an issue was identified where the chain ID contained in published feed filenames did not always match the chain ID currently registered in:

```text data/reference/chains.json ```

This can happen when a publisher uses a single publishing source to publish files for more than one chain ID.

For example, the City Market BinaProjects source is registered as:

```text chain_id: **7290058266241** name_en_normalized: city market client: BinaProjectsClient ```

However, the files discovered from the same publishing source also contain:

```text **7290058288090** ```

Therefore, the source publishes:

```text **7290058266241** **7290058288090** ```

while only `**7290058266241**` was initially known to the canonical chain registry.

This creates two separate problems:

## Metziah needs to detect chain IDs that are actually appearing in publisher feeds.

## The newly observed chain IDs need to be associated with the correct chain/store metadata without causing the same publishing source to be downloaded multiple times.

## Decision

Separate **publishing-source registration** from **observed chain-ID registration**.

The canonical:

```text data/reference/chains.json ```

continues to contain the chain entries that define the publishing sources Metziah should download from.

A second registry:

```text data/reference/chains_extra.json ```

is used for additional chain IDs discovered inside published filenames.

An entry in `chains_extra.json` represents an additional chain ID belonging to an already-known publishing source.

It does **not** represent another publishing source.

This distinction prevents the same publisher from being downloaded twice.

## Filename Monitoring

A monitoring file was introduced at:

```text monitoring/data/filename_chains.json ```

This file is generated from:

```text data/reference/file_tracking.csv ```

The existing `file_tracking.csv` contains information extracted from discovered filenames, including:

```text filename source file_type chain_id sub_chain_id store_id file_date file_size downloaded ```

The monitoring process groups the observed chain IDs by publishing source.

For example:

```json
{
    *city market*: {
    *chain_ids*: [
    *7290058266241*,
    *7290058288090*
    ],
    *chain_names*: {
    *7290058266241*: *city market*
    },
    *unknown_chain_ids*: [
    *7290058288090*
    ],
    *unknown_store_ids*: {
    *7290058288090*: [
    *069*
    ]
    },
    *placeholder_chain_ids*: []
    }
}
```

This provides a persistent snapshot of what chain IDs each publisher is actually emitting.

## Known Chain IDs

A chain ID is considered known when it exists in:

```text data/reference/chains.json ```

Known chain IDs are included under:

```text chain_names ```

using their registered normalized name.

For example:

```json
*chain_names*: {
    *7290058266241*: *city market*
}
```

This allows the monitoring output to show which observed IDs are already understood by the canonical registry.

## Unknown Chain IDs

If a chain ID appears in `file_tracking.csv` but is not present in `chains.json`, it is placed under:

```text unknown_chain_ids ```

For example:

```json
*unknown_chain_ids*: [
    *7290058288090*
]
```

The monitoring process also records the actual store IDs associated with the unknown chain.

These are stored under:

```text unknown_store_ids ```

For example:

```json
*unknown_store_ids*: {
    *7290058288090*: [
    *069*
    ]
}
```

Only the actual `store_id` values are recorded.

The full filenames or complete file-tracking records are intentionally not duplicated into `filename_chains.json`.

This keeps the monitoring file focused on the chain discrepancy rather than becoming another copy of `file_tracking.csv`.

## Placeholder Chain IDs

Known placeholder IDs such as:

```text **0000000000000** ```

are treated separately from genuinely unknown chain IDs.

They are placed under:

```text placeholder_chain_ids ```

rather than being treated as a missing chain registry entry.

This prevents placeholder values from generating unnecessary extra-chain records.

## Multiple Chain IDs From One Source

The monitoring process also detects when a single publishing source emits multiple chain IDs.

For example:

```text Source: city market

**7290058266241** **7290058288090** ```

A warning is logged indicating that the source publishes multiple chain IDs.

This is important because the publishing source and the chain ID are not necessarily one-to-one.

The publisher should therefore not automatically be duplicated simply because another chain ID appears in its filenames.

## Extra Chain Registry

When an unknown chain ID is found, the monitoring process attempts to create an entry in:

```text data/reference/chains_extra.json ```

The extra chain receives a copy of the metadata from the known chain belonging to the same publishing source.

For example:

```json
{
    *7290058288090*: {
    *Chain_name_store_file*: *סיטי צפריר בע\*מ*,
    *Chain_name_gov_page*: *סיטי מרקט*,
    *name_he_normalized*: *סיטי מרקט*,
    *name_en_normalized*: *city market*,
    *web_site*: *[https://city-market.co.il/*,](https://city-market.co.il/*,)
    *publishing_in*: "[https://citymarketkiryatgat.binaprojects.com/Main.aspx",](https://citymarketkiryatgat.binaprojects.com/Main.aspx*,)
    *client*: *BinaProjectsClient"
    }
}
```

The metadata is copied from the known chain:

```text **7290058266241** ```

but the chain ID itself becomes:

```text **7290058288090** ```

## Safety Rule for Automatic Extra Chains

An extra chain is automatically generated only when the source has exactly **one known non-placeholder chain ID**.

For example:

```text source: city market

known: **7290058266241**

unknown: **7290058288090** ```

This is unambiguous, so the unknown ID can safely inherit the known chain's metadata.

If a source has multiple known chain IDs, the monitoring process does not guess which one the unknown chain belongs to.

Instead, it logs an error and does not automatically create the extra-chain entry.

This prevents incorrect metadata from being assigned merely because multiple chains happen to share a publisher.

## Why `chains_extra.json` Is Separate

`get_publishing_sources()` continues to use only:

```text data/reference/chains.json ```

This is intentional.

If the following were both added to `chains.json`:

```text **7290058266241** **7290058288090** ```

and both had:

```text client: BinaProjectsClient ```

the publishing-source discovery code could interpret them as two sources and download the same BinaProjects publication twice.

Instead:

```text
chains.json
    ↓
publishing sources

chains_extra.json
    ↓
additional observed chain IDs
```

This keeps source discovery and chain-ID recognition separate.

## Store Registry Enrichment

The second part of the process handles stores that were originally registered under the known chain ID but are actually appearing in feed filenames under the newly observed chain ID.

A generic enrichment script was introduced at:

```text utils/stores/data_enrichmentchainsid_normalizer.py ```

Its input is:

```text monitoring/data/filename_chains.json ```

and the existing store registry:

```text data/stores/{name_en_normalized}.json ```

The process is generic and does not contain City Market-specific logic.

It uses the source name from `filename_chains.json` to locate the corresponding store **JSON**.

For example:

```text source: city market ```

maps to:

```text data/stores/city market.json ```

## Store ID Matching

The store ID contained in a feed filename may be zero-padded.

For example, the filename monitoring data may contain:

```text **069** ```

while the existing store registry contains:

```json
{
    *chain_id*: *7290058266241*,
    *store_id*: *69*,
    *name*: *חדרה*,
    *address*: *הנשיא 10*,
    *city*: *חדרה*,
    *zip_code*: *3842222*,
    *latitude*: 32.**4406137**,
    *longitude*: 34.**9159141**
}
```

The enrichment process therefore checks both representations.

It first attempts the padded representation:

```text **069** ```

and then falls back to the unpadded representation:

```text 69 ```

This allows feed filenames and existing store registries to use different store-ID formatting without preventing the match.

## Chain ID Enrichment Example

The monitoring process identifies:

```text source: city market unknown chain ID: **7290058288090** store ID: **069** ```

The existing store registry contains:

```text store_id: 69 chain_id: **7290058266241** ```

The enrichment process recognizes:

```text **069** = 69 ```

and changes only the chain ID:

```text **7290058266241** ```

to:

```text **7290058288090** ```

The store's other metadata remains unchanged.

Therefore:

```json
{
    *chain_id*: *7290058288090*,
    *store_id*: *69*,
    *name*: *חדרה*,
    *address*: *הנשיא 10*,
    *city*: *חדרה*,
    *zip_code*: *3842222*,
    *latitude*: 32.**4406137**,
    *longitude*: 34.**9159141**
}
```

The enrichment does not recreate the store or replace its metadata. It only corrects the chain ID associated with the existing store.

## Missing Store IDs

If an unknown chain ID has a store ID recorded in:

```text unknown_store_ids ```

but no matching store can be found in the corresponding store **JSON** using either representation, the enrichment process logs the problem.

For example:

```text **069** ```

is checked first, followed by:

```text 69 ```

If neither exists, the store is not modified.

This prevents the enrichment process from inventing store records.

## Missing Store Registry

If the source has unknown chain IDs but the corresponding:

```text data/stores/{source}.json ```

does not exist, the process logs the missing store registry rather than attempting to create one.

The enrichment process therefore operates only on existing store registries.

## Separation of Responsibilities

The resulting architecture separates the responsibilities of the different files and processes.

### `file_tracking.csv`

Records the files actually discovered from publishers.

```text What files were observed? ```

### `filename_chains.json`

Analyzes those filenames and records:

```text Which chain IDs does each source publish? Which IDs are unknown? Which store IDs belong to those unknown IDs? ```

### `chains.json`

Defines:

```text Which publishing sources should Metziah use? ```

### `chains_extra.json`

Defines:

```text Which additional chain IDs have been observed and belong to an already-known publishing source? ```

### `data/stores/*.json`

Contains:

```text Store metadata and the chain ID currently assigned to each store. ```

### `data_enrichmentchainsid_normalizer.py`

Reconciles:

```text
Observed filename chain ID
        ↓
Known store
        ↓
Updated store chain ID
```

## Result

The workflow now detects chain-ID discrepancies automatically instead of requiring them to be manually discovered by inspecting `file_tracking.csv`.

The process is:

```text
Publisher files
      ↓
file_tracking.csv
      ↓
filename_chains.json
      ↓
unknown chain ID detected
      ↓
unknown_store_ids identified
      ↓
chains_extra.json generated
      ↓
store registry enrichment
      ↓
store receives the chain ID actually observed in the feed
```

For the City Market example:

```text
BinaProjects source
        ↓
**7290058266241**
**7290058288090**
        ↓
**7290058288090** is unknown
        ↓
store **069** identified
        ↓
store 69 found in city market.json
        ↓
chain_id changed:
**7290058266241** → **7290058288090**
```

## Reason

The purpose of this system is to prevent the canonical chain registry from being forced to represent every chain ID that happens to appear in a publisher's filenames.

A publisher's publication endpoint and the chain IDs contained within its files are separate concepts.

The canonical registry therefore remains focused on publishing sources, while the monitoring system observes the actual feed contents and identifies additional chain IDs.

The extra-chain registry then provides the missing metadata required by the store-processing and database-seeding stages.

This also makes the process reusable across publishers. The logic does not depend on City Market specifically and can handle the same situation if another publisher begins emitting an additional chain ID in the future.

## Consequences

**Positive**

- Detects previously unknown chain IDs automatically.
- Shows which publisher/source emitted each unknown ID.
- Records the actual affected store IDs.
- Prevents manual inspection of `file_tracking.csv` for every discrepancy.
- Avoids duplicating publishing sources.
- Keeps `chains.json` focused on actual publishing sources.
- Allows additional chain IDs to be recognized by store and database processing.
- Automatically enriches existing stores with the chain ID observed in the feed.
- Handles zero-padded and non-padded store IDs.
- Does not invent stores when a matching store cannot be found.
- Uses a generic mechanism that can work across publishers.

**Negative**

- `chains_extra.json` must be kept synchronized with the observed publishing data.
- Automatic extra-chain creation is intentionally restricted when multiple known chains could be possible sources.
- Store enrichment depends on the existing store registry containing the affected store.
- A missing or incorrectly named store **JSON** prevents automatic enrichment.
- Chain-ID changes discovered through filenames require monitoring and validation.

## Future Considerations

If the same publisher repeatedly changes or adds chain IDs, the monitoring history should be used to determine whether the IDs represent:

- a permanent chain change,
- an additional sub-chain,
- a duplicate publishing identifier,
- or a temporary publisher-side change.

If an extra chain ID is eventually confirmed as a permanent independent publishing source, it can be promoted from:

```text chains_extra.json ```

to:

```text chains.json ```

and given its own publishing-source configuration.

Until then, the extra ID remains separate so that Metziah does not accidentally download the same publication multiple times.