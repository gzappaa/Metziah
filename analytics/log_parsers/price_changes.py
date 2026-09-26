# analytics/log_parsers/price_changes.py
"""
Parses logs/price_changes.log : per-chain add/change/remove counts, same-run
reintroduction detection, majority-of-chain removals, substantial price
changes, and inter-store / inter-chain correlation (the latter gated on the
item_code actually being a universal barcode in `products` — otherwise the
same numeric code can mean a different product in a different chain).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from analytics.log_parsers import common
from analytics.log_parsers.common import LogEntry

SUBSTANTIAL_PRICE_CHANGE_PCT = 20.0
MAJORITY_REMOVED_PCT = 50.0

PRICE_ADDED_RE = re.compile(
    r"^PRICE ADDED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) item_code=(?P<item_code>\S+)"
    r"(?: name=(?P<name>.*?))? price=(?P<price>[\d.]+)$"
)
PRICE_CHANGED_RE = re.compile(
    r"^PRICE CHANGED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) item_code=(?P<item_code>\S+)"
    r"(?: name=(?P<name>.*?))? old_price=(?P<old_price>[\d.]+) new_price=(?P<new_price>[\d.]+) "
    r"old_unit_price=(?P<old_unit_price>[\d.]+) new_unit_price=(?P<new_unit_price>[\d.]+)$"
)
ITEM_REMOVED_RE = re.compile(
    r"^ITEM REMOVED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) item_code=(?P<item_code>\S+)"
    r"(?: name=(?P<name>.*?))? \(was price=(?P<price>[\d.]+)\)$"
)


def parse(paths: list[Path]) -> tuple[dict, list[str]]:
    entries: list[LogEntry] = []
    for p in paths:
        entries.extend(common.iter_log_entries(p))
    entries.sort(key=lambda e: e.timestamp)

    chains = common.load_chains()

    added, changed, removed = [], [], []
    for e in entries:
        if e.level != "INFO" or e.logger != "price_changes":
            continue
        msg = e.message
        if (m := PRICE_ADDED_RE.match(msg)):
            added.append({"timestamp": e.timestamp, **m.groupdict()})
        elif (m := PRICE_CHANGED_RE.match(msg)):
            changed.append({"timestamp": e.timestamp, **m.groupdict()})
        elif (m := ITEM_REMOVED_RE.match(msg)):
            removed.append({"timestamp": e.timestamp, **m.groupdict()})

    # -- DB lookups (best-effort) --------------------------------------------
    all_item_codes = {r["item_code"] for r in added + changed + removed}
    all_chain_ids = {r["chain_id"] for r in added + changed + removed}

    universal_codes, universal_err = common.safe_db_call(
        common.fetch_universal_product_codes, all_item_codes, default=set()
    )
    store_counts, store_counts_err = common.safe_db_call(
        common.fetch_store_counts, all_chain_ids, default={}
    )
    db_unavailable = bool(universal_err or store_counts_err)

    # -- per-chain counts -----------------------------------------------------
    per_chain = defaultdict(lambda: {"added": 0, "changed": 0, "removed": 0})
    for r in added:
        per_chain[r["chain_id"]]["added"] += 1
    for r in changed:
        per_chain[r["chain_id"]]["changed"] += 1
    for r in removed:
        per_chain[r["chain_id"]]["removed"] += 1

    # -- duplicate item_code events within the same store/run -----------------
    events_by_store_item = defaultdict(list)
    for kind, bucket in (("added", added), ("changed", changed), ("removed", removed)):
        for r in bucket:
            events_by_store_item[(r["chain_id"], r["store_id"], r["item_code"])].append(kind)
    duplicate_events = [
        {"chain_id": cid, "store_id": sid, "item_code": code, "events": kinds}
        for (cid, sid, code), kinds in events_by_store_item.items()
        if len(kinds) > 1
    ]

    # -- reintroduced same run (ITEM REMOVED then PRICE ADDED, same store/item) --
    removed_index = defaultdict(list)  # (chain_id, store_id, item_code) -> [timestamps]
    for r in removed:
        removed_index[(r["chain_id"], r["store_id"], r["item_code"])].append(r["timestamp"])

    reintroduced = []
    for r in added:
        key = (r["chain_id"], r["store_id"], r["item_code"])
        prior_removals = [t for t in removed_index.get(key, []) if t < r["timestamp"]]
        if prior_removals:
            reintroduced.append({
                "chain_id": r["chain_id"], "store_id": r["store_id"], "item_code": r["item_code"],
                "removed_at": max(prior_removals).isoformat(), "added_at": r["timestamp"].isoformat(),
            })

    # -- majority-of-chain removals ---------------------------------------------
    removed_by_chain_item = defaultdict(set)
    for r in removed:
        removed_by_chain_item[(r["chain_id"], r["item_code"])].add(r["store_id"])

    majority_removed = []
    for (cid, code), stores in removed_by_chain_item.items():
        total = store_counts.get(cid)
        if total:
            pct = len(stores) / total * 100
            if pct >= MAJORITY_REMOVED_PCT:
                majority_removed.append({
                    "chain_id": cid, "chain_name": common.chain_name(cid, chains), "item_code": code,
                    "stores_affected": len(stores), "total_stores": total, "pct": round(pct, 1),
                })

    # -- cross-chain removed (universal products only) --------------------------
    removed_by_item_chain = defaultdict(set)
    for r in removed:
        if r["item_code"] in universal_codes:
            removed_by_item_chain[r["item_code"]].add(r["chain_id"])
    cross_chain_removed = [
        {"item_code": code, "chains": sorted(cids), "chain_names": [common.chain_name(c, chains) for c in sorted(cids)]}
        for code, cids in removed_by_item_chain.items() if len(cids) > 1
    ]

    # -- inter-store price changes (same chain) ----------------------------------
    changed_by_chain_item = defaultdict(list)
    for r in changed:
        changed_by_chain_item[(r["chain_id"], r["item_code"])].append(r)
    inter_store_changes = [
        {
            "chain_id": cid, "chain_name": common.chain_name(cid, chains), "item_code": code,
            "stores": [{"store_id": r["store_id"], "old_price": r["old_price"], "new_price": r["new_price"]} for r in rs],
        }
        for (cid, code), rs in changed_by_chain_item.items()
        if len({r["store_id"] for r in rs}) > 1
    ]

    # -- inter-chain price changes (universal products only) ---------------------
    changed_by_item_chain = defaultdict(set)
    for r in changed:
        if r["item_code"] in universal_codes:
            changed_by_item_chain[r["item_code"]].add(r["chain_id"])
    inter_chain_changes = [
        {"item_code": code, "chains": sorted(cids), "chain_names": [common.chain_name(c, chains) for c in sorted(cids)]}
        for code, cids in changed_by_item_chain.items() if len(cids) > 1
    ]

    # -- substantial price changes ------------------------------------------------
    substantial_changes = []
    for r in changed:
        old, new = float(r["old_price"]), float(r["new_price"])
        if old == 0:
            pct = 100.0 if new > 0 else 0.0
        else:
            pct = abs(new - old) / old * 100
        if pct >= SUBSTANTIAL_PRICE_CHANGE_PCT:
            substantial_changes.append({
                "chain_id": r["chain_id"], "chain_name": common.chain_name(r["chain_id"], chains),
                "store_id": r["store_id"], "item_code": r["item_code"], "name": r.get("name"),
                "old_price": r["old_price"], "new_price": r["new_price"], "pct_change": round(pct, 1),
            })

    data = {
        "run_date": common.resolve_run_date(entries),
        "db_unavailable": db_unavailable,
        "counts": {"added": len(added), "changed": len(changed), "removed": len(removed)},
        "per_chain": {
            cid: {"chain_name": common.chain_name(cid, chains), **counts} for cid, counts in per_chain.items()
        },
        "duplicate_events_same_store": duplicate_events,
        "reintroduced_same_run": reintroduced,
        "majority_removed_from_chain": majority_removed,
        "cross_chain_removed": cross_chain_removed,
        "inter_store_price_changes": inter_store_changes,
        "inter_chain_price_changes": inter_chain_changes,
        "substantial_price_changes": substantial_changes,
    }
    return data, _render_txt(data)


def _render_txt(data: dict) -> list[str]:
    lines = ["=== Price changes report ===", f"Run date: {data['run_date']}"]
    if data["db_unavailable"]:
        lines.append("(DB unavailable — cross-chain/majority checks were skipped)")
    lines += ["", f"Added: {data['counts']['added']}  Changed: {data['counts']['changed']}  Removed: {data['counts']['removed']}", ""]

    lines.append("-- Per chain --")
    for cid, v in data["per_chain"].items():
        lines.append(f"  {v['chain_name']} ({cid}): +{v['added']} / ~{v['changed']} / -{v['removed']}")
    lines.append("")

    if data["substantial_price_changes"]:
        lines.append(f"-- Substantial price changes (>= {SUBSTANTIAL_PRICE_CHANGE_PCT}%) --")
        for c in data["substantial_price_changes"]:
            lines.append(f"  [{c['chain_name']}] store {c['store_id']} item {c['item_code']} "
                         f"({c.get('name') or 'no name'}): {c['old_price']} -> {c['new_price']} ({c['pct_change']}%)")
        lines.append("")

    if data["reintroduced_same_run"]:
        lines.append("-- Reintroduced same run (removed then re-added) --")
        for r in data["reintroduced_same_run"]:
            lines.append(f"  chain {r['chain_id']} store {r['store_id']} item {r['item_code']}: "
                         f"removed {r['removed_at']} -> added {r['added_at']}")
        lines.append("")

    if data["majority_removed_from_chain"]:
        lines.append(f"-- Removed from >= {MAJORITY_REMOVED_PCT}% of chain's stores --")
        for r in data["majority_removed_from_chain"]:
            lines.append(f"  {r['chain_name']} item {r['item_code']}: {r['stores_affected']}/{r['total_stores']} ({r['pct']}%)")
        lines.append("")

    if data["cross_chain_removed"]:
        lines.append("-- Same universal product removed across multiple chains --")
        for r in data["cross_chain_removed"]:
            lines.append(f"  item {r['item_code']}: {', '.join(r['chain_names'])}")
        lines.append("")

    if data["inter_store_price_changes"]:
        lines.append("-- Same item price-changed in multiple stores of the same chain --")
        for r in data["inter_store_price_changes"]:
            lines.append(f"  {r['chain_name']} item {r['item_code']}: {len(r['stores'])} store(s)")
        lines.append("")

    if data["inter_chain_price_changes"]:
        lines.append("-- Same universal product price-changed across multiple chains --")
        for r in data["inter_chain_price_changes"]:
            lines.append(f"  item {r['item_code']}: {', '.join(r['chain_names'])}")
        lines.append("")

    if data["duplicate_events_same_store"]:
        lines.append("-- Same item, multiple event types, same store/run --")
        for r in data["duplicate_events_same_store"]:
            lines.append(f"  chain {r['chain_id']} store {r['store_id']} item {r['item_code']}: {r['events']}")

    return lines