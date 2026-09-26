# analytics/log_parsers/promo_changes.py
"""
Parses logs/promo_changes.log : promotion coverage (%-of-chain-stores via
`promotions` table), promo-item add/change/remove per-chain summaries,
discount-vs-normal-price lookup (via `prices`, batched with unnest()),
and inter-store/inter-chain checks gated on `products` table membership,
same as price_changes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from db import get_connection
from analytics.log_parsers import common
from analytics.log_parsers.common import LogEntry

SUBSTANTIAL_PROMO_CHANGE_PCT = 20.0

PROMOTION_ADDED_RE = re.compile(
    r"^PROMOTION ADDED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) "
    r"promotion_id=(?P<promotion_id>\S+) description=(?P<description>.*)$"
)
PROMOTION_REMOVED_RE = re.compile(
    r"^PROMOTION REMOVED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) "
    r"promotion_id=(?P<promotion_id>\S+)(?: description=(?P<description>.*))?$"
)
PROMO_ITEM_ADDED_RE = re.compile(
    r"^PROMO ITEM ADDED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) "
    r"promotion_id=(?P<promotion_id>\S+) group_id=(?P<group_id>\S+) item_code=(?P<item_code>\S+) "
    r"name=(?P<name>.*?) discounted_price=(?P<discounted_price>[\d.]+)$"
)
PROMO_ITEM_CHANGED_RE = re.compile(
    r"^PROMO ITEM CHANGED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) "
    r"promotion_id=(?P<promotion_id>\S+) group_id=(?P<group_id>\S+) item_code=(?P<item_code>\S+) "
    r"name=(?P<name>.*?) old=\((?P<old>.*?)\) new=\((?P<new>.*?)\)$"
)
PROMO_ITEM_REMOVED_RE = re.compile(
    r"^PROMO ITEM REMOVED chain_id=(?P<chain_id>\S+) store_id=(?P<store_id>\S+) "
    r"promotion_id=(?P<promotion_id>\S+) group_id=(?P<group_id>\S+) item_code=(?P<item_code>\S+) "
    r"name=(?P<name>.*)$"
)
DECIMAL_RE = re.compile(r"Decimal\('([\d.]+)'\)")


def _first_decimal(tuple_text: str) -> float | None:
    m = DECIMAL_RE.search(tuple_text)
    return float(m.group(1)) if m else None


def fetch_promotion_store_counts(chain_id: str, promotion_ids: set[str]) -> dict[str, int]:

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT promotion_id, COUNT(DISTINCT store_id) FROM promotions "
                "WHERE chain_id = %s AND promotion_id = ANY(%s) GROUP BY promotion_id",
                (chain_id, list(promotion_ids)),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def fetch_prices(tuples: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], float]:
    """tuples: (chain_id, store_id, item_code) -> price, in one batched query."""
    if not tuples:
        return {}


    chain_ids, store_ids, item_codes = zip(*tuples)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.chain_id, p.store_id, p.item_code, p.price
                FROM prices p
                JOIN unnest(%s::text[], %s::text[], %s::text[])
                    AS lookup(chain_id, store_id, item_code)
                ON p.chain_id = lookup.chain_id
                   AND p.store_id = lookup.store_id
                   AND p.item_code = lookup.item_code
                """,
                (list(chain_ids), list(store_ids), list(item_codes)),
            )
            return {
                (row[0], row[1], row[2]): float(row[3])
                for row in cur.fetchall()
                if row[3] is not None
            }
    finally:
        conn.close()


def parse(paths: list[Path]) -> tuple[dict, list[str]]:
    entries: list[LogEntry] = []
    for p in paths:
        entries.extend(common.iter_log_entries(p))
    entries.sort(key=lambda e: e.timestamp)

    chains = common.load_chains()

    promo_added, promo_removed = [], []
    item_added, item_changed, item_removed = [], [], []

    for e in entries:
        if e.level != "INFO" or e.logger != "promo_changes":
            continue
        msg = e.message
        if (m := PROMOTION_ADDED_RE.match(msg)):
            promo_added.append({"timestamp": e.timestamp, **m.groupdict()})
        elif (m := PROMOTION_REMOVED_RE.match(msg)):
            promo_removed.append({"timestamp": e.timestamp, **m.groupdict()})
        elif (m := PROMO_ITEM_ADDED_RE.match(msg)):
            item_added.append({"timestamp": e.timestamp, **m.groupdict()})
        elif (m := PROMO_ITEM_CHANGED_RE.match(msg)):
            d = m.groupdict()
            d["old_price"] = _first_decimal(d.pop("old"))
            d["new_price"] = _first_decimal(d.pop("new"))
            item_changed.append({"timestamp": e.timestamp, **d})
        elif (m := PROMO_ITEM_REMOVED_RE.match(msg)):
            item_removed.append({"timestamp": e.timestamp, **m.groupdict()})

    all_item_codes = {r["item_code"] for r in item_added + item_changed + item_removed}
    universal_codes, universal_err = common.safe_db_call(
        common.fetch_universal_product_codes, all_item_codes, default=set()
    )
    store_counts, store_counts_err = common.safe_db_call(
        common.fetch_store_counts, {r["chain_id"] for r in promo_added}, default={}
    )
    db_unavailable = bool(universal_err or store_counts_err)

    # -- per-chain counts -----------------------------------------------------
    per_chain = defaultdict(lambda: {"promotions_added": 0, "promotions_removed": 0,
                                      "items_added": 0, "items_changed": 0, "items_removed": 0})
    for r in promo_added:
        per_chain[r["chain_id"]]["promotions_added"] += 1
    for r in promo_removed:
        per_chain[r["chain_id"]]["promotions_removed"] += 1
    for r in item_added:
        per_chain[r["chain_id"]]["items_added"] += 1
    for r in item_changed:
        per_chain[r["chain_id"]]["items_changed"] += 1
    for r in item_removed:
        per_chain[r["chain_id"]]["items_removed"] += 1

    # -- promotion coverage (%-of-chain-stores) --------------------------------
    promo_ids_by_chain = defaultdict(set)
    for r in promo_added:
        promo_ids_by_chain[r["chain_id"]].add(r["promotion_id"])

    coverage = []
    for cid, promo_ids in promo_ids_by_chain.items():
        counts, err = common.safe_db_call(fetch_promotion_store_counts, cid, promo_ids, default={})
        total_stores = store_counts.get(cid)
        for pid, store_count in counts.items():
            entry = {
                "chain_id": cid, "chain_name": common.chain_name(cid, chains), "promotion_id": pid,
                "stores_with_promotion": store_count,
            }
            if total_stores:
                entry["total_stores"] = total_stores
                entry["pct"] = round(store_count / total_stores * 100, 1)
            coverage.append(entry)

    # -- discount vs normal price (promo item added) ---------------------------
    # -- discount vs normal price (promo item added) ---------------------------
    lookup_tuples = [(r["chain_id"], r["store_id"], r["item_code"]) for r in item_added]
    prices, price_err = common.safe_db_call(fetch_prices, lookup_tuples, default={})

    item_added_events = []
    discounts = []
    for r in item_added:
        key = (r["chain_id"], r["store_id"], r["item_code"])
        normal_price = prices.get(key)
        discounted = float(r["discounted_price"])
        event = {
            "chain_id": r["chain_id"], "chain_name": common.chain_name(r["chain_id"], chains),
            "store_id": r["store_id"], "promotion_id": r["promotion_id"], "group_id": r["group_id"],
            "item_code": r["item_code"], "name": r["name"],
            "discounted_price": discounted,
            "normal_price": normal_price,
            "discount_pct": round((normal_price - discounted) / normal_price * 100, 1) if normal_price else None,
            "timestamp": r["timestamp"].isoformat(),
        }
        item_added_events.append(event)
        if normal_price:
            discounts.append(event)

    # -- substantial promo item price changes ------------------------------------
    substantial_changes = []
    for r in item_changed:
        old, new = r.get("old_price"), r.get("new_price")
        if old is None or new is None:
            continue
        pct = (100.0 if new > 0 else 0.0) if old == 0 else abs(new - old) / old * 100
        if pct >= SUBSTANTIAL_PROMO_CHANGE_PCT:
            substantial_changes.append({
                "chain_id": r["chain_id"], "chain_name": common.chain_name(r["chain_id"], chains),
                "store_id": r["store_id"], "item_code": r["item_code"], "name": r["name"],
                "old_price": old, "new_price": new, "pct_change": round(pct, 1),
            })

    # -- inter-store / inter-chain removed (universal products only) -------------
    removed_by_chain_item = defaultdict(set)
    removed_by_item_chain = defaultdict(set)
    for r in item_removed:
        removed_by_chain_item[(r["chain_id"], r["item_code"])].add(r["store_id"])
        if r["item_code"] in universal_codes:
            removed_by_item_chain[r["item_code"]].add(r["chain_id"])

    inter_store_removed = [
        {"chain_id": cid, "chain_name": common.chain_name(cid, chains), "item_code": code, "store_count": len(stores)}
        for (cid, code), stores in removed_by_chain_item.items() if len(stores) > 1
    ]
    inter_chain_removed = [
        {"item_code": code, "chains": sorted(cids), "chain_names": [common.chain_name(c, chains) for c in sorted(cids)]}
        for code, cids in removed_by_item_chain.items() if len(cids) > 1
    ]

    data = {
        "run_date": common.resolve_run_date(entries),
        "db_unavailable": db_unavailable,
        "counts": {
            "promotions_added": len(promo_added), "promotions_removed": len(promo_removed),
            "items_added": len(item_added), "items_changed": len(item_changed), "items_removed": len(item_removed),
        },
        "per_chain": {
            cid: {"chain_name": common.chain_name(cid, chains), **counts} for cid, counts in per_chain.items()
        },
        "promotion_coverage": coverage,
        "discounts": discounts,
        "item_added_events": item_added_events,  # <-- new: raw per-item records for downstream filtering (e.g. nearby-store notifications)
        "substantial_promo_item_changes": substantial_changes,
        "inter_store_items_removed": inter_store_removed,
        "inter_chain_items_removed": inter_chain_removed,
    }
    return data, _render_txt(data)


def _render_txt(data: dict) -> list[str]:
    c = data["counts"]
    lines = ["=== Promo changes report ===", f"Run date: {data['run_date']}"]
    if data["db_unavailable"]:
        lines.append("(DB unavailable — coverage/discount/cross-chain checks were partially skipped)")
    lines += ["",
              f"Promotions: +{c['promotions_added']} / -{c['promotions_removed']}   "
              f"Items: +{c['items_added']} / ~{c['items_changed']} / -{c['items_removed']}", ""]

    lines.append("-- Per chain --")
    for cid, v in data["per_chain"].items():
        lines.append(f"  {v['chain_name']} ({cid}): promos +{v['promotions_added']}/-{v['promotions_removed']}, "
                     f"items +{v['items_added']}/~{v['items_changed']}/-{v['items_removed']}")
    lines.append("")

    if data["promotion_coverage"]:
        lines.append("-- Promotion coverage --")
        for r in data["promotion_coverage"]:
            pct = f" ({r['pct']}%)" if "pct" in r else ""
            total = f"/{r['total_stores']}" if "total_stores" in r else ""
            lines.append(f"  {r['chain_name']} promo {r['promotion_id']}: {r['stores_with_promotion']}{total}{pct}")
        lines.append("")

    if data["discounts"]:
        lines.append("-- Discounts (promo item added) --")
        for r in data["discounts"]:
            lines.append(f"  {r['chain_name']} store {r['store_id']} {r['name']}: "
                         f"{r['normal_price']} -> {r['discounted_price']} ({r['discount_pct']}% off)")
        lines.append("")

    if data["substantial_promo_item_changes"]:
        lines.append(f"-- Substantial promo item price changes (>= {SUBSTANTIAL_PROMO_CHANGE_PCT}%) --")
        for r in data["substantial_promo_item_changes"]:
            lines.append(f"  {r['chain_name']} store {r['store_id']} {r['name']}: "
                         f"{r['old_price']} -> {r['new_price']} ({r['pct_change']}%)")
        lines.append("")

    if data["inter_store_items_removed"]:
        lines.append("-- Same promo item removed in multiple stores of same chain --")
        for r in data["inter_store_items_removed"]:
            lines.append(f"  {r['chain_name']} item {r['item_code']}: {r['store_count']} store(s)")
        lines.append("")

    if data["inter_chain_items_removed"]:
        lines.append("-- Same universal product removed from promos across multiple chains --")
        for r in data["inter_chain_items_removed"]:
            lines.append(f"  item {r['item_code']}: {', '.join(r['chain_names'])}")

    return lines