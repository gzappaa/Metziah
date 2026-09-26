# analytics/log_parsers/scheduler.py
"""
Parses logs/scheduler.log* : phase timings (start->end pairs with elapsed
time), per-source discovery counts, missing-file warnings, per-chain
no-items/no-prices/no-valid-promotions warnings, product discovery events,
per-file price/promo load stats, and the file_sizes enrichment summary.
"""

from __future__ import annotations

import re
from pathlib import Path

from analytics.log_parsers import common
from analytics.log_parsers.common import LogEntry

# --- phase start/end pairs -------------------------------------------------

PHASES = [
    dict(key="file_tracking_update", label="File tracking update",
         start_re=re.compile(r"^Updating file tracking$"),
         end_re=re.compile(r"^File tracking updated: (?P<new_files>\d+) new file\(s\)$")),
    dict(key="pricesfull_download", label="PriceFull download",
         start_re=re.compile(r"^Starting pricesfull download$"),
         end_re=re.compile(r"^PriceFull download finished: (?P<new_files>\d+) new file\(s\)$")),
    dict(key="prices_download", label="Price download",
         start_re=re.compile(r"^Starting prices download\s*$"),
         end_re=re.compile(r"^Finished\. Downloaded (?P<new_files>\d+) Price file\(s\) total\.$")),
    dict(key="pricesfull_load", label="PriceFull load",
         start_re=re.compile(r"^Loading (?P<pending>\d+) pending PriceFull file\(s\)$"),
         end_re=re.compile(r"^Successfully loaded (?P<loaded>\d+) PriceFull file\(s\)$")),
    dict(key="price_load", label="Price load",
         start_re=re.compile(r"^Loading (?P<pending>\d+) pending Price file\(s\)$"),
         end_re=re.compile(r"^Successfully loaded (?P<loaded>\d+) Price file\(s\)$")),
    dict(key="promosfull_download", label="PromoFull download",
         start_re=re.compile(r"^Starting promosfull download$"),
         end_re=re.compile(r"^PromoFull download finished: (?P<new_files>\d+) new file\(s\)$")),
    dict(key="promos_download", label="Promo download",
         start_re=re.compile(r"^Starting promos download$"),
         end_re=re.compile(r"^Promo download finished: (?P<new_files>\d+) new file\(s\)$")),
    dict(key="promosfull_load", label="PromoFull load",
         start_re=re.compile(r"^Loading (?P<pending>\d+) pending PromoFull file\(s\)$"),
         end_re=re.compile(r"^Successfully loaded (?P<loaded>\d+) PromoFull file\(s\)$")),
    dict(key="promo_load", label="Promo load",
         start_re=re.compile(r"^Loading (?P<pending>\d+) eligible Promo files$"),
         end_re=re.compile(r"^Successfully loaded (?P<loaded>\d+) Promo file\(s\)$")),
]

SOURCE_COUNT_RE = re.compile(r"^(?P<source>[A-Za-z]+): (?P<count>\d+) today's file\(s\) total$")
INSERTED_RE = re.compile(r"^Inserted (?P<inserted>\d+) new file\(s\) out of (?P<discovered>\d+) discovered$")

NO_PRICEFULL_RE = re.compile(r"^No PriceFull files found for (?P<name>.+)$")
NO_PRICE_RE = re.compile(r"^No Price files found for (?P<name>.+)$")

NO_ITEMS_PARSED_RE = re.compile(r"^No items parsed from (?P<path>.+)$")
NO_PRICES_FOUND_RE = re.compile(r"^No prices found in (?P<path>.+)$")
NO_VALID_PROMOTIONS_RE = re.compile(r"^No valid promotions with promotion_id found in (?P<path>.+)$")
CHAIN_FROM_PATH_RE = re.compile(r"/data/feeds/(?P<chain_id>\d+)/")

PRODUCT_DISCOVERY_RE = re.compile(
    r"^New-product discovery: (?P<new_products>\d+) new product\(s\), "
    r"(?P<store_product_records>\d+) store_product record\(s\) from (?P<from_files>\d+) file\(s\) "
    r"\((?P<already_existed>\d+) candidate item_code\(s\) already existed\)$"
)

PRICE_FILE_LOAD_RE = re.compile(
    r"^(?P<filename>\S+): type=(?P<file_type>\w+) snapshot=(?P<snapshot>True|False) "
    r"chain_id=(?P<chain_id>\d+) store_id=(?P<store_id>\S+) items=(?P<items>\d+) removed=(?P<removed>\d+)$"
)

PROMO_FILE_LOAD_RE = re.compile(
    r"^(?P<filename>\S+): file_type=(?P<file_type>\w+) chain_id=(?P<chain_id>\d+) store_id=(?P<store_id>\S+) "
    r"promotions=(?P<promotions>\d+) items=(?P<items>\d+) removed_promotions=(?P<removed_promotions>\d+) "
    r"removed_groups=(?P<removed_groups>\d+) removed_items=(?P<removed_items>\d+)$"
)

FILE_SIZES_FINISHED_RE = re.compile(r"^Finished: updated=(?P<updated>\d+) missing=(?P<missing>\d+)$")
FILE_SIZES_NOT_FOUND_RE = re.compile(r"^File not found: id=\d+ path=.+$")  # explicitly ignored per spec


def _chain_from_path(path: str) -> str:
    m = CHAIN_FROM_PATH_RE.search(path)
    return m.group("chain_id") if m else "unknown"


def parse(paths: list[Path]) -> tuple[dict, list[str]]:
    entries: list[LogEntry] = []
    for p in paths:
        entries.extend(common.iter_log_entries(p))
    entries.sort(key=lambda e: e.timestamp)

    chains = common.load_chains()

    open_phases: dict[str, LogEntry] = {}
    phase_timings: list[dict] = []

    source_file_counts: dict[str, int] = {}
    file_tracking_inserted: dict | None = None

    pricefull_missing: list[str] = []
    price_missing: list[str] = []

    no_items_parsed: dict[str, int] = {}
    no_prices_found: dict[str, int] = {}
    no_valid_promotions: dict[str, int] = {}

    product_discovery_events: list[dict] = []

    price_file_loads: dict[str, dict] = {}   # chain_id -> aggregate
    promo_file_loads: dict[str, dict] = {}   # chain_id -> aggregate

    file_sizes_finished: dict | None = None

    unmatched_samples: list[str] = []
    unmatched_count = 0

    for e in entries:
        msg = e.message

        if e.level == "ERROR":
            continue  # handled by errors.py

        # -- phase start/end --------------------------------------------------
        matched_phase = False
        for phase in PHASES:
            if phase["key"] not in open_phases and phase["start_re"].match(msg):
                open_phases[phase["key"]] = e
                matched_phase = True
                break
            if phase["key"] in open_phases:
                m = phase["end_re"].match(msg)
                if m:
                    start_e = open_phases.pop(phase["key"])
                    elapsed = (e.timestamp - start_e.timestamp).total_seconds()
                    phase_timings.append({
                        "phase": phase["key"],
                        "label": phase["label"],
                        "start": start_e.timestamp.isoformat(),
                        "end": e.timestamp.isoformat(),
                        "elapsed_seconds": elapsed,
                        "elapsed_human": common.format_timedelta(elapsed),
                        **m.groupdict(),
                    })
                    matched_phase = True
                    break
        if matched_phase:
            continue

        # -- file tracking discovery -----------------------------------------
        if e.logger == "utils.file_tracking.load_file_tracking":
            if (m := SOURCE_COUNT_RE.match(msg)):
                source_file_counts[m.group("source")] = int(m.group("count"))
                continue
            if (m := INSERTED_RE.match(msg)):
                file_tracking_inserted = {
                    "inserted": int(m.group("inserted")),
                    "discovered": int(m.group("discovered")),
                }
                continue

        # -- missing file warnings --------------------------------------------
        if (m := NO_PRICEFULL_RE.match(msg)):
            pricefull_missing.append(m.group("name"))
            continue
        if (m := NO_PRICE_RE.match(msg)):
            price_missing.append(m.group("name"))
            continue

        # -- per-chain no items / no prices / no valid promotions -------------
        if (m := NO_ITEMS_PARSED_RE.match(msg)):
            cid = _chain_from_path(m.group("path"))
            no_items_parsed[cid] = no_items_parsed.get(cid, 0) + 1
            continue
        if (m := NO_PRICES_FOUND_RE.match(msg)):
            cid = _chain_from_path(m.group("path"))
            no_prices_found[cid] = no_prices_found.get(cid, 0) + 1
            continue
        if (m := NO_VALID_PROMOTIONS_RE.match(msg)):
            cid = _chain_from_path(m.group("path"))
            no_valid_promotions[cid] = no_valid_promotions.get(cid, 0) + 1
            continue

        # -- product discovery --------------------------------------------------
        if (m := PRODUCT_DISCOVERY_RE.match(msg)):
            product_discovery_events.append({
                "timestamp": e.timestamp.isoformat(),
                **{k: int(v) for k, v in m.groupdict().items()},
            })
            continue

        # -- per-file price load -------------------------------------------------
        if (m := PRICE_FILE_LOAD_RE.match(msg)):
            cid = m.group("chain_id")
            agg = price_file_loads.setdefault(cid, {
                "chain_name": common.chain_name(cid, chains),
                "files": 0, "items": 0, "removed": 0,
                "snapshot_true": 0, "snapshot_false": 0,
                "by_type": {},
            })
            agg["files"] += 1
            agg["items"] += int(m.group("items"))
            agg["removed"] += int(m.group("removed"))
            agg["snapshot_true" if m.group("snapshot") == "True" else "snapshot_false"] += 1
            agg["by_type"][m.group("file_type")] = agg["by_type"].get(m.group("file_type"), 0) + 1
            continue

        # -- per-file promo load -------------------------------------------------
        if (m := PROMO_FILE_LOAD_RE.match(msg)):
            cid = m.group("chain_id")
            agg = promo_file_loads.setdefault(cid, {
                "chain_name": common.chain_name(cid, chains),
                "files": 0, "promotions": 0, "items": 0,
                "removed_promotions": 0, "removed_groups": 0, "removed_items": 0,
            })
            agg["files"] += 1
            agg["promotions"] += int(m.group("promotions"))
            agg["items"] += int(m.group("items"))
            agg["removed_promotions"] += int(m.group("removed_promotions"))
            agg["removed_groups"] += int(m.group("removed_groups"))
            agg["removed_items"] += int(m.group("removed_items"))
            continue

        # -- file size enrichment ------------------------------------------------
        if e.logger == "utils.file_tracking.data_enrichment.populate_file_sizes":
            if FILE_SIZES_NOT_FOUND_RE.match(msg):
                continue  # explicitly excluded from the report
            if (m := FILE_SIZES_FINISHED_RE.match(msg)):
                file_sizes_finished = {k: int(v) for k, v in m.groupdict().items()}
                continue

        # -- anything else: don't drop it silently, just count it -------------
        unmatched_count += 1
        if len(unmatched_samples) < 20:
            unmatched_samples.append(f"[{e.logger}] {msg}")

    total_elapsed = None
    if phase_timings:
        first_start = min(datetime_from_iso(p["start"]) for p in phase_timings)
        end_ts = (
            datetime_from_iso_str(file_sizes_finished_ts(entries))
            if file_sizes_finished
            else None
        )
        # fall back to the last phase's end if we never saw the file-sizes line
        last_end = max(datetime_from_iso(p["end"]) for p in phase_timings)
        end_ts = end_ts or last_end
        total_elapsed = (end_ts - first_start).total_seconds()

    data = {
        "run_date": common.resolve_run_date(entries),
        "total_pipeline_elapsed_seconds": total_elapsed,
        "total_pipeline_elapsed_human": common.format_timedelta(total_elapsed) if total_elapsed else None,
        "phase_timings": phase_timings,
        "source_file_counts": source_file_counts,
        "file_tracking_inserted": file_tracking_inserted,
        "pricefull_missing_count": len(pricefull_missing),
        "pricefull_missing": pricefull_missing,
        "price_missing_count": len(price_missing),
        "price_missing": price_missing,
        "no_items_parsed_by_chain": {
            cid: {"chain_name": common.chain_name(cid, chains), "count": c}
            for cid, c in no_items_parsed.items()
        },
        "no_prices_found_by_chain": {
            cid: {"chain_name": common.chain_name(cid, chains), "count": c}
            for cid, c in no_prices_found.items()
        },
        "no_valid_promotions_by_chain": {
            cid: {"chain_name": common.chain_name(cid, chains), "count": c}
            for cid, c in no_valid_promotions.items()
        },
        "product_discovery_events": product_discovery_events,
        "price_file_loads_by_chain": price_file_loads,
        "promo_file_loads_by_chain": promo_file_loads,
        "file_sizes_finished": file_sizes_finished,
        "unmatched_line_count": unmatched_count,
        "unmatched_samples": unmatched_samples,
    }

    txt = _render_txt(data)
    return data, txt


# small local helpers to avoid re-parsing ISO strings all over the place
def datetime_from_iso(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s)


def datetime_from_iso_str(s):
    from datetime import datetime
    return datetime.fromisoformat(s) if s else None


def file_sizes_finished_ts(entries: list[LogEntry]) -> str | None:
    for e in entries:
        if e.logger == "utils.file_tracking.data_enrichment.populate_file_sizes" and FILE_SIZES_FINISHED_RE.match(e.message):
            return e.timestamp.isoformat()
    return None


def _render_txt(data: dict) -> list[str]:
    lines = ["=== Scheduler report ===", f"Run date: {data['run_date']}", ""]

    if data["total_pipeline_elapsed_human"]:
        lines.append(f"Total pipeline time: {data['total_pipeline_elapsed_human']}")
    lines.append("")

    lines.append("-- Phase timings --")
    for p in data["phase_timings"]:
        extra = ", ".join(f"{k}={v}" for k, v in p.items()
                           if k not in ("phase", "label", "start", "end", "elapsed_seconds", "elapsed_human"))
        lines.append(f"{p['label']}: {p['elapsed_human']}" + (f" ({extra})" if extra else ""))
    lines.append("")

    if data["source_file_counts"]:
        lines.append("-- Files discovered per source (today) --")
        for src, count in data["source_file_counts"].items():
            lines.append(f"  {src}: {count}")
        if data["file_tracking_inserted"]:
            fti = data["file_tracking_inserted"]
            lines.append(f"  Inserted {fti['inserted']} new file(s) out of {fti['discovered']} discovered")
        lines.append("")

    if data["pricefull_missing"]:
        lines.append(f"-- No PriceFull files found ({data['pricefull_missing_count']} source(s)) --")
        lines.append("  " + ", ".join(data["pricefull_missing"]))
        lines.append("")
    if data["price_missing"]:
        lines.append(f"-- No Price files found ({data['price_missing_count']} source(s)) --")
        lines.append("  " + ", ".join(data["price_missing"]))
        lines.append("")

    for label, key in (
        ("No items parsed", "no_items_parsed_by_chain"),
        ("No prices found", "no_prices_found_by_chain"),
        ("No valid promotions", "no_valid_promotions_by_chain"),
    ):
        if data[key]:
            lines.append(f"-- {label}, per chain --")
            for cid, v in data[key].items():
                lines.append(f"  {v['chain_name']} ({cid}): {v['count']}")
            lines.append("")

    if data["product_discovery_events"]:
        lines.append("-- New-product discovery --")
        total_new = sum(ev["new_products"] for ev in data["product_discovery_events"])
        total_records = sum(ev["store_product_records"] for ev in data["product_discovery_events"])
        lines.append(f"  {total_new} new product(s), {total_records} store_product record(s) across "
                      f"{len(data['product_discovery_events'])} run(s)")
        lines.append("")

    if data["price_file_loads_by_chain"]:
        lines.append("-- Price/PriceFull file loads, per chain --")
        for cid, agg in data["price_file_loads_by_chain"].items():
            lines.append(f"  {agg['chain_name']} ({cid}): {agg['files']} file(s), "
                         f"{agg['items']} item(s), {agg['removed']} removed "
                         f"(types: {agg['by_type']})")
        lines.append("")

    if data["promo_file_loads_by_chain"]:
        lines.append("-- Promo/PromoFull file loads, per chain --")
        for cid, agg in data["promo_file_loads_by_chain"].items():
            lines.append(f"  {agg['chain_name']} ({cid}): {agg['files']} file(s), "
                         f"{agg['promotions']} promotion(s), {agg['items']} item(s), "
                         f"removed: {agg['removed_promotions']} promo(s)/"
                         f"{agg['removed_groups']} group(s)/{agg['removed_items']} item(s)")
        lines.append("")

    if data["file_sizes_finished"]:
        fs = data["file_sizes_finished"]
        lines.append(f"-- File size enrichment: updated={fs['updated']} missing={fs['missing']} --")
        lines.append("")

    if data["unmatched_line_count"]:
        lines.append(f"-- {data['unmatched_line_count']} unrecognized line(s) (parser may need updating) --")
        for s in data["unmatched_samples"]:
            lines.append(f"  {s}")

    return lines