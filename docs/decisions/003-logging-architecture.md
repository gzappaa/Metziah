# Decision 003: Logging architecture -- entry-point logs vs. isolated audit logs

# Update — 2026-08-16

The logging architecture has changed since this decision was written.

The pipeline download/load components are no longer launched by `scheduler.py` as separate subprocesses. The scheduler now calls their functions directly, in-process.

Because of this, `scheduler.py` is now the single root logging owner for the entire pipeline. All pipeline execution logs — including price, PriceFull, promo, PromoFull, file tracking, API/client, parser, loader, and scheduler logs — go to:

- Normal runs: `logs/scheduler.log`
- Test runs: `logs/scheduler.test.log`

Pipeline components such as `prices.py`, `pricesfull.py`, `promos.py`, and `promosfull.py` should no longer call `setup_logging()` themselves. They should only use:

logger = logging.getLogger(__name__)

and rely on the root logger configured by `scheduler.py`.

The isolated audit/change logs remain independent:

- `logs/price_changes.log`
- `logs/promo_changes.log`

The original decision below is retained as historical context. Its subprocess-based assumptions and consequences are no longer current.



Date: 2026-08-09

## Context

The pipeline runs in two different ways:

- `scheduler.py` imports `utils/update_prices.py` directly and runs it
  **in-process**.
- `downloaders/prices.py`, `pricesfull.py`, `promosfull.py` are run by
  `scheduler.py` as **subprocesses** (separate Python interpreters,
  spawned via `subprocess`/cron).

Several modules used by both -- `clients/laibcatalog.py`,
`parsers/xml.py`, and others -- only do:

```python
logger = logging.getLogger(__name__)
```

They never attach a handler of their own. A logger with no handler
propagates its messages upward through the dotted-name hierarchy (e.g.
`clients.laibcatalog` -> `clients` -> root) until it finds an ancestor
that has one. Whichever ancestor is configured is where the message
actually gets written.

Logging configuration only applies within the process it's set up in --
a handler attached in `scheduler.py` has no effect inside `prices.py`,
since that runs as a separate interpreter. Each subprocess entry point
has to configure its own logging.

Separately, some logs are audit trails, not run narration -- e.g.
`update_prices.py`'s price/metadata diffs, and `get_stores.py`'s store
diffs. These need to stay in their own file regardless of what else runs
in the same process, so they can be parsed independently
(`analyze_price_log.py`).

---

## Decision

One shared module, `logging_config.py`, at the project root, exposing
three functions:

### `setup_logging(name)`
For daily pipeline entry points: `scheduler.py`, `prices.py`,
`pricesfull.py`, `promosfull.py`. Configures the **root** logger for
that process, writing to `logs/<name>.log`. Because it's root, anything
in that process using a plain `logging.getLogger(__name__)` -- including
`laibcatalog.py` -- is captured too, labeled with its own logger name
(e.g. `[clients.laibcatalog]`).

### `setup_general_logging()`
For ad-hoc/manual scripts outside the daily pipeline (e.g.
`get_stores.py`). A thin wrapper: `setup_logging("general")`. Same
root-based capture behavior, always writing to `logs/general.log`.

### `setup_isolated_logging(name)`
For logs that must be consumed independently and never mixed with
anything else in the same process. Builds a **named** logger with
`propagate = False`, its own handler, writing only to `logs/<name>.log`.
Used by `update_prices.py` (`price_changes.log`) and `get_stores.py`'s
store-diff output (`store_changes.log`).

All three share one formatter and `RotatingFileHandler` setup (5MB per
file, 5 backups), and one environment-based level selection via
`METZIA_ENV` (`dev` / `test` / `prod`, defaulting to `dev`), read once at
import time.

```text
Process runs setup_logging("prices")
        |
        v
   root logger configured -> logs/prices.log
        |
        +-- prices.py's own logger.info(...) -> prices.log
        |
        +-- clients.laibcatalog (no handler of its own)
                 |
                 v
            propagates to root -> prices.log
                 (labeled "[clients.laibcatalog]")

Meanwhile, in the SAME process, update_prices.py:
   setup_isolated_logging("price_changes")
        |
        v
   named logger, propagate=False -> logs/price_changes.log
   (never reaches root, never mixes with prices.log)
```

---

## Reason

Configuring root everywhere would capture third-party/library logging
(laibcatalog, parsers) correctly, but can't also give audit logs like
`price_changes.log` guaranteed isolation -- only one thing can configure
root per process.

Using named, non-propagating loggers everywhere would give isolation,
but loses the "capture everything from this run" behavior --
`clients.laibcatalog` would propagate to root, find nothing configured
there, and its messages would be dropped.

Three explicit functions make the intent obvious at each call site:
`setup_logging` = "this is a pipeline run, capture everything in it,"
`setup_general_logging` = "this is a one-off script, dump it in the
shared bucket," `setup_isolated_logging` = "this is an audit trail, keep
it pure."

---

## Consequences

### Positive
- Subprocess entry points automatically capture library-level logging
  (laibcatalog retries/errors) in their own file, with no awareness
  needed from those modules.
- `price_changes.log` and `store_changes.log` stay fully isolated
  regardless of what else runs in the same process.
- Rotation and formatting are consistent everywhere, defined once.
- `METZIA_ENV` gives a single, explicit hook for dev/test/prod log
  verbosity, ready to extend once real environment separation exists.

### Negative
- Only one thing can meaningfully configure root per process. If two
  modules in the same process both call `setup_logging` with different
  names, the first call wins and the second silently no-ops (guarded by
  `if root_logger.handlers`). This is fine under the current assumption
  that `prices.py` / `pricesfull.py` / `promosfull.py` run only as
  standalone subprocesses, never imported into another entry point.
- Logger names used with `setup_isolated_logging` (`price_changes`,
  `store_changes`) are implicitly reserved -- calling `setup_logging`
  with the same name would return an already-configured logger instead
  of erroring.
- All ad-hoc scripts share `general.log`, so retrieving one script's
  history later means grepping a shared file rather than opening a
  dedicated one.

---

## Future considerations
- Add a guard comment (or assertion) in `logging_config.py` documenting
  which logger names are reserved for `setup_isolated_logging`.
- If `prices.py` / `pricesfull.py` / `promosfull.py` are ever imported
  directly instead of run only as subprocesses, revisit the
  first-caller-wins root configuration assumption.
- Consider splitting `general.log` further once enough ad-hoc scripts
  exist that grepping it becomes unwieldy.