"""
Daily cron entry point: email a COUNT of new promotion items (PROMO ITEM
ADDED) that appeared today at stores near you, across all chains, and
write the full per-item detail to reports/{date}/report_promos_details.json/.txt.

Design notes:
- No chain filter: analytics/log_parsers/promo_changes.py is the single
  source of truth for parsing, name lookup, and normal-price lookup (via
  the `prices` table) -- this script does not re-parse the log itself and
  does not hit the DB a second time for promotion details. What
  promo_changes.parse() already resolved is what gets reported and emailed.
- "Nearby" is chain-agnostic: get_nearby_store_ids(chain_id=None) returns
  (chain_id, store_id) pairs for ANY chain within MAX_STORE_DISTANCE_KM of
  the fixed USER_LAT/USER_LON.
- The email body is counts only (per nearby store) -- item-level detail
  goes to the promos_details report, not the email.
- notified_promotions.log dedups by identity (chain_id, store_id,
  promotion_id, group_id, item_code) so re-running the same day's log
  doesn't re-email the same promotion.

Run manually:
    python -m utils.promo_notifications

Cron (once per day):
    0 8 * * * cd /path/to/metziah && /path/to/venv/bin/python -m utils.promo_notifications
"""

from __future__ import annotations

import sys
from pathlib import Path

# utils/promo_notifications.py
PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR))

from config import settings
from logging_config import setup_logging
from db import get_connection
from database.repository import get_nearby_store_ids
from analytics.log_parsers import common, promo_changes
from analytics.notifications.mailer import send_email


LOG_DIR = PROJECT_DIR / "logs"
PROMO_CHANGES_LOGS = sorted(LOG_DIR.glob("promo_changes.log*"))

NOTIFIED_FILE = PROJECT_DIR / "data" / "notified_promotions.log"
REPORTS_DIR = PROJECT_DIR / "analytics" / "reports"

_IDENTITY_FIELDS = ("chain_id", "store_id", "promotion_id", "group_id", "item_code")

logger = setup_logging("promo_notifications")


def event_key(event: dict) -> str:
    return "|".join(str(event[f]) for f in _IDENTITY_FIELDS)


def load_notified_keys() -> set[str]:
    if not NOTIFIED_FILE.exists():
        return set()

    with NOTIFIED_FILE.open(encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_notified(key: str) -> None:
    NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)

    with NOTIFIED_FILE.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


def build_digest_email(events: list[dict]) -> tuple[str, str]:
    """
    Count-only digest, per nearby store -- no item names/prices in the
    email itself. Full detail lives in the promos_details report.
    """
    total = len(events)

    counts: dict[str, int] = {}
    for e in events:
        store_label = f"{e['chain_name']} store {e['store_id']}"
        counts[store_label] = counts.get(store_label, 0) + 1

    subject = f"New supermarket promotions near you ({total})"

    lines = [
        f"{store}: {count} new promotion{'s' if count != 1 else ''}"
        for store, count in sorted(counts.items())
    ]

    body = (
        "\n".join(lines)
        + "\n\nSee today's promos_details report for item-level detail."
    )

    return subject, body


def _render_details_txt(data: dict) -> list[str]:
    lines = [
        "=== Nearby promos detail ===",
        f"Run date: {data['run_date']}",
        f"Nearby stores: {data['nearby_store_count']}",
        f"Total promo items at nearby stores: {data['total_nearby_promo_items']}",
        "",
    ]

    for e in data["items"]:
        if e["normal_price"] is not None:
            price_part = (
                f"{e['normal_price']} -> {e['discounted_price']} "
                f"({e['discount_pct']}% off)"
            )
        else:
            price_part = (
                f"{e['discounted_price']} "
                "(normal price unknown)"
            )

        lines.append(
            f"  {e['chain_name']} store {e['store_id']} "
            f"{e['name']}: {price_part}"
        )

    return lines


def run() -> None:
    if settings.USER_LAT is None or settings.USER_LON is None:
        logger.error("USER_LAT/USER_LON not configured -- aborting")
        return

    if not PROMO_CHANGES_LOGS:
        logger.info("No promo changes logs found in %s", LOG_DIR)
        return

    logger.info(
        "Parsing %d promo changes log(s): %s",
        len(PROMO_CHANGES_LOGS),
        ", ".join(path.name for path in PROMO_CHANGES_LOGS),
    )

    data, _ = promo_changes.parse(PROMO_CHANGES_LOGS)
    run_date = data["run_date"]

    with get_connection() as conn:
        nearby = get_nearby_store_ids(
            conn,
            settings.USER_LAT,
            settings.USER_LON,
            settings.MAX_STORE_DISTANCE_KM,
            chain_id=None,
        )

    nearby_stores = set(nearby)  # {(chain_id, store_id), ...}

    logger.info("Found %d nearby store(s)", len(nearby_stores))

    if not nearby_stores:
        return

    nearby_events = [
        e
        for e in data["item_added_events"]
        if (e["chain_id"], e["store_id"]) in nearby_stores
    ]

    logger.info(
        "Found %d promo item(s) added at nearby stores",
        len(nearby_events),
    )

    # Always write the full-detail report, independent of notification state.
    details_data = {
        "run_date": run_date,
        "nearby_store_count": len(nearby_stores),
        "total_nearby_promo_items": len(nearby_events),
        "items": nearby_events,
    }

    common.write_report(
        "promos_details",
        run_date,
        details_data,
        _render_details_txt(details_data),
        REPORTS_DIR,
    )

    if not nearby_events:
        return

    # Email only the never-notified subset.
    notified_keys = load_notified_keys()

    to_notify = [
        e for e in nearby_events
        if event_key(e) not in notified_keys
    ]

    if not to_notify:
        logger.info(
            "All nearby promotions already notified, nothing new to email"
        )
        return

    subject, body = build_digest_email(to_notify)

    if send_email(subject, body):
        logger.info(
            "Notification email sent for %d new promotion(s)",
            len(to_notify),
        )

        for e in to_notify:
            mark_notified(event_key(e))
    else:
        logger.error(
            "Notification email failed for %d promotion(s)",
            len(to_notify),
        )


if __name__ == "__main__":
    run()