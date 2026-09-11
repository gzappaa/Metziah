# Decision 006: File Size Metadata and HTML Size Retrieval Strategy

**Date:** **2026**-09-09

## Context


File size is useful metadata in its own right.

For price and promotion feeds, the size of a file can provide useful information **before the file is downloaded**. This is particularly valuable for `PriceFull`, `Price`, `PromoFull`, and `Promo` files, where file size can help distinguish snapshots, identify unexpectedly small or large files, and detect changes between files without immediately downloading their contents.

The `file_tracking` table therefore stores:

```text file_size **BIGINT** ```

The value is stored in **bytes**.

File size is treated as metadata about the published file, rather than something that only exists after downloading the file.

Different publishers expose this information differently:

- Some APIs provide the file size directly as part of their file metadata.
- Some **HTML** listings provide the file size directly in the **HTML** table.
- Some publishers do not provide it in the listing, but the downloadable **URL** responds to a `**HEAD**` request containing `Content-Length`.
- Some publishers require a `**GET**` request to obtain the `Content-Length`.
- Some publishers provide no practical way to obtain the size before downloading.

The implementation therefore uses the cheapest and most direct available source for each publisher.

## Decision

Metziah will collect and store file size whenever it can be obtained **before downloading the file**, without requiring the actual feed contents to be downloaded.

The general source hierarchy is:

## Use a file size explicitly provided by the publisher's API or HTML listing.

## Otherwise, use a `HEAD` request when the publisher supports it reliably. ## Otherwise, use a lightweight `GET` request with streaming when necessary. ## If the size cannot be obtained reliably, leave `file_size` as `NULL`.

The system does not require every publisher to provide file size.

The purpose is to make file size an available piece of file metadata whenever the source makes it reasonably accessible.

## Why File Size Is Useful Before Downloading

Obtaining the file size before downloading provides several advantages.

### Change Detection

File size can be used as an early indication that a newly published file differs from another file.

For example, if two `PriceFull` files have substantially different sizes, Metziah can identify that difference before downloading either file.

File size is not treated as a replacement for content comparison, but it is useful as an inexpensive first-level signal.

### Snapshot Validation

A newly published snapshot that is unexpectedly tiny can be suspicious.

For example, a normal `PriceFull` file may usually contain hundreds of thousands of products. If a newly published snapshot is suddenly only a few kilobytes, its size can immediately indicate that something may be wrong.

This allows Metziah to identify suspicious files before spending resources downloading and processing them.

### Historical Analysis

Because file size is stored in `file_tracking`, Metziah can retain historical information about how feed sizes change over time.

This can later be useful for identifying:

- unusually large or small snapshots,
- changes in publisher feed structure,
- sudden reductions in published data,
- unexpected growth,
- possible incomplete files,
- differences between successive snapshots.

### Download Planning

Knowing the size before downloading can eventually allow Metziah to make better decisions about download scheduling and resource usage.

Large files can be identified before the download begins rather than only after the download is already underway.

### Cheap Metadata

A file size request is substantially cheaper than downloading and parsing a potentially large compressed feed.

The goal is therefore to obtain useful information about a file without requiring its contents.

## HTML Publishers

**HTML**-based publishers required a slightly different implementation because the available information differs between websites.

The generic **HTML** client was extended so that a candidate file can optionally contain:

```text file_size ```

The **HTML** source configuration determines whether a file size column exists.

This keeps publisher-specific **HTML** structure in configuration rather than adding publisher-specific logic to the generic **HTML** client.

For example, when a website contains the file size directly in a table row, the configured column can be used to extract it.

If the **HTML** listing already provides the size, no additional **HTTP** request is necessary.

## Shufersal Special Case

Shufersal presented a particular performance problem.

The Shufersal website contains a large number of paginated file listings, and accessing those pages is relatively slow.

The initial approach considered using `**HEAD**` requests to obtain the size of every discovered file, as this would provide a relatively simple and generic mechanism.

However, applying that approach to Shufersal was not practical.

Shufersal has too many pages and the listing itself is already expensive to process. Performing additional requests for every discovered file would add significant overhead to an already slow discovery process.

The goal was therefore to avoid making Shufersal even slower simply to obtain file size metadata.

Fortunately, Shufersal's **HTML** listing already provides the file size directly in the table.

A Shufersal row contains information equivalent to:

```text Download link Date 2.57 KB GZ price Store Filename ... ```

Therefore, the file size can be extracted directly from the **HTML** instead of performing a separate `**HEAD**` request.

The Shufersal configuration consequently specifies the appropriate file-size column:

```text file_size_column: 2 ```

The filename continues to come from the download **URL**.

Shufersal therefore does **not** need individual `**HEAD**` requests for its files.

## Tradeoff

This required making the **HTML** configuration slightly more complicated.

Instead of having one universal rule such as:

```text all **HTML** files → **HEAD** request → Content-Length ```

the configuration now allows the source to specify how file size should be obtained.

This is intentional.

The small increase in configuration complexity avoids a much larger performance cost for Shufersal.

The tradeoff is:

```text
Slightly more complicated configuration
        ↓
Avoid hundreds/thousands of unnecessary requests
        ↓
Use size already present in Shufersal's **HTML**
        ↓
Much better discovery performance
```

In other words, the implementation accepts a small amount of publisher-specific configuration because the alternative would be significantly more expensive **HTTP** traffic.

## HTML Size Request Policy

For **HTML** publishers, the current strategy is:

### Size already present in HTML

Use the value extracted from the **HTML**.

No additional request is made.

### City Market

Use a `**GET**` request with streaming when the size is not present in the listing.

### Hazi Hinam and Super Pharm

Use `**HEAD**` requests when running with `--slow` and the **HTML** listing does not provide the size.

### Shufersal

Use the size provided directly by the **HTML** listing.

Do **not** perform individual `**HEAD**` requests for Shufersal files.

### Other HTML publishers

Do not perform size requests unless explicitly configured to do so.

This prevents the generic **HTML** discovery mechanism from unexpectedly generating large numbers of additional **HTTP** requests.

## `--slow` Behavior

The `--slow` option controls additional size discovery when obtaining the size requires extra **HTTP** requests.

Without `--slow`, Metziah avoids these additional requests where appropriate.

When `--slow` is enabled, the system attempts to obtain sizes through the configured mechanism.

However, a size already provided by the publisher is still used directly because no additional request is necessary.

Therefore, `--slow` should be understood as:

```text allow additional work to obtain file-size metadata ```

rather than:

```text always make another request for every file ```

## Request Concurrency

Where additional **HTTP** requests are necessary, they should be performed concurrently with a controlled concurrency limit rather than strictly sequentially.

BinaProjects already follows this approach using a size-request concurrency limit.

The same principle should be applied to **HTML** publishers that require multiple `**HEAD**` or `**GET**` size requests.

This provides a balance between:

- reducing total discovery time,
- avoiding one request blocking the next,
- and preventing an uncontrolled number of simultaneous requests against a publisher.

The concurrency limit is controlled centrally rather than creating an unlimited number of requests.

## Logging

Successful file-size requests are not necessarily visible in the logs for every implementation.

For example, the BinaProjects **HTTP** client explicitly logs successful `**GET**` requests:

```text **GET** ... -> **HTTP** **200** ```

The generic `get_file_size()` helper historically only logged failures.

Therefore, a successful `**HEAD**` request may occur without producing a corresponding:

```text **HEAD** ... -> **HTTP** **200** ```

log entry.

The absence of such a log line does not mean that the `**HEAD**` request was not performed.

This is an implementation difference in logging rather than a difference in whether the request occurred.

## Result

File tracking now stores file size as part of the metadata associated with discovered files.

The resulting model is:

```text
Publisher
    ↓
File discovery
    ↓
Filename + file date + store + source
    ↓
File size obtained when reasonably available
    ↓
file_tracking
    ↓
Download
    ↓
Load / processing
```

File size can therefore exist in the database **before the corresponding feed is downloaded**.

This gives Metziah an inexpensive metadata layer around its feed-tracking system rather than making all useful information dependent on downloading the actual file.

## Reason

File size is useful information about a published feed and can often be obtained much more cheaply than downloading the feed itself.

The system therefore benefits from recording it as early as possible.

At the same time, different publishers expose file size in different ways. A universal request strategy would either fail for some publishers or generate unnecessary traffic and excessive discovery times.

Shufersal demonstrated why this matters particularly clearly: its listing is slow and heavily paginated, making per-file `**HEAD**` requests an undesirable tradeoff. Since Shufersal already exposes the size in its **HTML**, extracting that value directly provides the same metadata without the additional network requests.

The resulting design intentionally favors:

**publisher-provided metadata → direct extraction → lightweight request → no size**

rather than forcing every publisher through the same mechanism.

## Consequences

**Positive**

- File size is available before downloading the feed whenever the publisher permits it.
- Provides an inexpensive signal for detecting changes between files.
- Can help identify suspicious or unexpectedly small snapshots.
- Enables historical analysis of feed sizes.
- Allows download planning based on expected file size.
- Avoids downloading files merely to determine their size.
- Uses publisher-provided sizes directly when available.
- Avoids unnecessary requests against slow publishers.
- Keeps publisher-specific behavior in configuration rather than hard-coding it into the generic **HTML** client.
- Shufersal avoids potentially hundreds or thousands of additional size requests.
- Controlled concurrency can significantly reduce the time required for external size requests.

**Negative**

- File size is not available for every publisher or every file.
- Different publishers require different mechanisms for obtaining size.
- **HTML** configuration is somewhat more complicated because file-size extraction differs between publishers.
- `--slow` can still generate additional network traffic.
- `**HEAD**`/`**GET**` behavior depends on how each publisher's server implements its downloadable files.
- File size alone cannot prove that two files contain different data; it is an early signal rather than a complete content comparison.

## Future Considerations

If a publisher begins exposing file size directly through its **API** or **HTML**, that source should be preferred over additional **HTTP** requests.

If additional publishers expose file size in their **HTML** listings, their configurations should use the **HTML** value rather than issuing `**HEAD**` requests.

If file-size requests become a significant part of discovery time, concurrency limits and request behavior should be reviewed per publisher.

File size may also be incorporated into future feed validation and change-detection logic, for example:

```text
same filename
- same file size
→ probably unchanged

different file size → definitely worth further inspection

unexpectedly small file → possible publishing problem ```

These should remain **signals**, not assumptions about file contents.