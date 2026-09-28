# Decision 005: Yellow Store Registry and Address/City Normalization

**Date:** **2026**-09-06

## Context

Yellow/Paz does not provide a `Stores` **XML** file through its publishedprices account.

For the other publishers in Metziah, store metadata and store IDs can normally be obtained from the publisher's `Stores` **XML**. Yellow/Paz was different: after checking the publishedprices account, no `Stores` file was available.

Because of this, the Yellow store registry could not be built using the standard Stores **XML** process.

A separate source of store information was therefore manually located on the Paz/Yellow website. The website provides a downloadable spreadsheet containing Yellow station information, including station IDs, station names, location/address information, and services.

The spreadsheet was downloaded and converted to:

```text data/reference/yellow_stations.csv ````

This **CSV** contains **263** stations.

The **CSV** is used as the **metadata source**, but it is not assumed to represent the complete set of currently published stores.

The actual set of stores published through the Yellow/Paz `publishedprices` account was determined independently by querying the account and examining its `PriceFull` files.

The comparison was performed using the following logic:

## Log in to the Yellow/Paz `publishedprices` account.

## Retrieve the available files. ## Identify `PriceFull` files belonging to chain `7290644700005`. ## Extract the `store_id` from each `PriceFull` filename. ## Compare those published store IDs against the station IDs in `yellow_stations.csv`.

The result was:

```text **CSV** stations:             **263** Published PriceFull stores: **242**

Present in both:          **238** Only in publishedprices:   4 Only in **CSV**:               25 ```

The four stores found in `publishedprices` but not in the manually obtained **CSV** were:

```text **891** **892** **6108** **6109** ```

The 25 **CSV**-only stations are ignored because they do not currently appear as published `PriceFull` stores.

Therefore, the `PriceFull` files are the source of truth for **which Yellow stores should exist in the Metziah store registry**, while the manually obtained Yellow spreadsheet is used to provide metadata for those stores.

## Decision

Build `data/stores/yellow.json` using the following source hierarchy:

### Store existence and store ID

Use the `PriceFull` files available through the Yellow/Paz `publishedprices` account.

Only store IDs that currently have a matching `PriceFull` file are included in the registry.

### Store metadata

For published store IDs that also exist in `yellow_stations.csv`, use the metadata from the **CSV**.

For published store IDs that do not exist in the **CSV**, include the store with unknown metadata rather than excluding it.

For example:

```json
{
    *chain_id*: *7290644700005*,
    *store_id*: *891*,
    *name*: *unknown*,
    *address*: "*,
    *city*: **,
    *zip_code*: null,
    *latitude*: null,
    *longitude": null
}
```

### CSV-only stations

Stations that exist in the manually obtained **CSV** but do not have a corresponding published `PriceFull` store are ignored.

This prevents stores that are listed on the Yellow website but are not currently publishing price data from entering the Metziah store registry.

## Address and City Normalization

The Yellow spreadsheet does not provide address and city as separate fields.

Instead, the location information is provided in a single field, generally using the final `-` separator between the address and locality.

Examples include:

```text כביש 40 מול מושב אלישמע בכניסה המזרחית של הוד השרון   - הוד השרון ```

and:

```text ליד שפרעם   - ביר אל-מכסור ```

The location data cannot reliably be separated using a simple regular expression because hyphens can occur both inside addresses and inside locality names.

For example:

```text ליד שפרעם   - ביר אל-מכסור ```

must produce:

```text address: ליד שפרעם city: ביר אל-מכסור ```

rather than incorrectly interpreting `ביר אל` as the locality.

Likewise:

```text הרצל **188** - תל אביב - יפו ```

must produce:

```text address: הרצל **188** city: תל אביב - יפו ```

rather than:

```text address: הרצל **188** - תל אביב city: יפו ```

Because the distinction is semantic rather than purely syntactic, AI-assisted normalization is used for the approximately **263** source records.

The AI normalization is instructed to:

- Separate the source location into `address` and `city`.
- Preserve hyphens that belong to locality names.
- Preserve hyphens that belong to addresses.
- Treat Israeli cities, towns, villages, and other localities as valid values for the `city` field.
- Preserve the locality name rather than attempting to reduce it to a technically defined *city*.
- Handle inconsistent whitespace around the separator.
- Leave missing information empty rather than inventing data.

## Special Cases

### `תל אביב - יפו`

`תל אביב - יפו` is treated as a single locality name.

The internal `-` must therefore remain part of the `city` value.

### Hyphenated localities

Localities such as:

```text ביר אל-מכסור דאלית אל-כרמל ```

must remain intact.

The hyphen inside the locality is not an address separator.

### Addresses containing hyphens

An address may itself contain a hyphen.

For example:

```text כביש חיפה - תל אביב ביציאה מחיפה   - חיפה ```

must produce:

```text address: כביש חיפה - תל אביב ביציאה מחיפה city: חיפה ```

The internal hyphen belongs to the address.

### Missing city

Some source records explicitly contain:

```text אין ציון עיר ```

This is treated as a placeholder meaning that no city/locality was supplied.

It is normalized to:

```text city: "" ```

No city is inferred from other information.

### Empty address

If the source contains a locality but no address, the address remains empty.

For example, row **379** (`דלית אל כרמל`) has no address supplied by the source.

The normalized result is:

```text address: "" city: דאלית אל-כרמל ```

This is considered valid incomplete source data.

## Result

Running:

```text python -m utils.stores.yellow_stores ```

currently produces:

```text Loading yellow_stations.csv... **CSV** stations: **263** Logging in to publishedprices... Requesting files... Published PriceFull stores: **242**

====================================================================== # YELLOW STORE REGISTRY Present in both:          **238** Only in publishedprices:  4 Only in **CSV**:              25

Published-only stores:
    **891**
    **892**
    **6108**
    **6109**

Wrote **242** stores to /home/dmin/metziah/data/stores/yellow.json ```

The resulting registry therefore contains ****242** stores**.

The **242** stores consist of:

- **238** stores with metadata from the Yellow spreadsheet.
- 4 published stores with unknown metadata.
- 25 **CSV**-only stations excluded from the registry.

## Reason

Yellow/Paz requires a different store-discovery process because it does not expose a `Stores` **XML** file through its publishedprices account.

The Yellow website spreadsheet was therefore manually located as an alternative metadata source.

However, the spreadsheet is not treated as the authoritative source for currently published stores. Store existence is determined independently from the actual `PriceFull` files available through publishedprices.

This separates two different concerns:

**Published `PriceFull` files → which stores exist in the feed**

**Yellow website spreadsheet → metadata for those stores**

This also prevents outdated or non-publishing stations from being added merely because they appear on the Yellow website.

AI is used only for the address/city normalization problem because the source location field contains ambiguous natural-language data that cannot reliably be handled by simple regex rules.

## Consequences

**Positive**

- Supports Yellow despite the absence of a `Stores` **XML** file.
- Uses actual published `PriceFull` files to determine the active store set.
- Uses an independently obtained official Yellow/Paz source for station metadata.
- Prevents **CSV**-only stations from being incorrectly registered.
- Keeps published stores even when metadata is missing.
- Handles complex Israeli locality names and hyphenated addresses.
- Does not invent missing addresses or localities.

**Negative**

- Yellow requires a different discovery process from publishers that provide `Stores` **XML**.
- The station metadata depends on the manually obtained Yellow spreadsheet.
- AI-assisted normalization introduces a non-deterministic processing step.
- The Yellow spreadsheet may become outdated and may need to be replaced or refreshed in the future.
- Published stores without matching metadata remain incomplete until their metadata can be obtained.

## Future Considerations

If Yellow/Paz begins publishing a `Stores` **XML** file through `publishedprices`, that source should be evaluated as the preferred store metadata source.

If Yellow provides a structured **API** or downloadable source with separate address and city fields, it should replace the AI normalization step.

The current approach should remain in place as long as:

- no Yellow `Stores` **XML** is available,
- `PriceFull` files remain the reliable source for published store IDs,
- and the Yellow website spreadsheet remains the available metadata source.

``` ```


# Update — 2026-09-20

On ****2026**-09-20**, Yellow/Paz began publishing a `Stores` **XML** file through its `publishedprices` account.

This provides a direct first-party source for Yellow store IDs and store metadata.

The newly available `Stores` **XML** is therefore now the preferred source for the Yellow store registry.

## Validation of the Previous Approach

The newly available **XML** also provided an opportunity to validate the previous **CSV**-based solution against the new first-party source.

The previous Yellow registry was compared against the newly obtained `Stores` **XML**.

Store IDs were normalized for matching so that different zero-padding representations were treated as the same store.

Address and city values were normalized before comparison to account for formatting differences such as whitespace, punctuation, and spacing around hyphens.

The comparison produced:

```text **XML** stores:              **242** Previous registry:       **242** Stores in both:          **237** **XML**-only:                  5 Previous-only:             5

For the **237** stores present in both registries:

**EXACT** / **NEAR**-**EXACT**       **173** / **237**  (73.00%) **VERY** **CLOSE**                17 / **237**  ( 7.17%) **CLOSE**                     37 / **237**  (15.61%) **PARTIAL**                    6 / **237**  ( 2.53%) **DIFFERENT**                  4 / **237**  ( 1.69%)

Overall:

>= 80% similarity:       **227** / **237**  (95.78%) >= 90% similarity:       **190** / **237**  (80.17%)

Most differences were formatting or representation differences rather than incorrect locality identification.

For example:

**XML**:        תל אביב -יפו Previous:   תל אביב - יפו

and:

**XML**:        **188** הרצל Previous:   הרצל  **188**

The five stores present only in the new **XML** were:

**213** **221** **248** **249** **618**

The five stores present only in the previous registry were:

**127** **197** **427** **6108** **6109**

The comparison therefore provides evidence that the previous **CSV**-based approach produced broadly similar address/city metadata, while also showing that the newly available **XML** should replace it as the authoritative source.

The comparison script was used only for validation and is not part of the production Yellow store pipeline.

### New Decision

The Yellow Stores **XML** is now the source of truth for the Yellow store registry.

The production flow is now:

Yellow/Paz publishedprices
        ↓
Stores **XML**
        ↓
data/stores/yellow.json

The previous architecture:

Published PriceFull files → store existence yellow_stations.csv       → metadata AI normalization          → address/city separation

is retired.

PriceFull files may still be used to independently verify published price-data coverage, but they are no longer required as the primary source for constructing the Yellow store registry.

### Archived Previous Implementation

The previous Yellow-specific implementation is no longer part of the production pipeline.

It is archived together with the source **CSV**:

data/archive/yellow/ ├── yellow_stores.py.txt └── yellow_stations_2026-09-06.csv

The archived script documents the exact implementation used when Yellow did not provide a Stores **XML** file.

It may be restored if Yellow/Paz stops publishing the Stores **XML** or if the **XML** becomes unusable.

### Updated Future Considerations

The Yellow Stores **XML** is now the preferred source for the Yellow store registry.

The previous **CSV**-based implementation should only be reconsidered if:

Yellow/Paz stops publishing the Stores **XML**, the **XML** becomes unavailable for an extended period, or the **XML** no longer provides sufficient store metadata.

If this happens, the archived **CSV** and previous yellow_stores.py implementation can be used as a fallback, subject to revalidation against the currently published PriceFull files.

So the chronology stays clean:

****2026**-09-06:** no **XML** → **CSV** + PriceFull solution → **242** stores.

****2026**-09-20:** **XML** appears → compare old solution against it → retire old production approach → archive it → use **XML** going forward.