# utils/promo_notifications.py
"""
Daily cron entry point: notify by email when a new promotion item
(PROMO ITEM ADDED) appears at a nearby store.

Flow:
    logs/promo_changes(.test).log
        -> parse PROMO ITEM ADDED lines
        -> filter to nearby stores (PostGIS, chain_id + USER_LAT/LON)
        -> skip already-notified events (data/notified_promotions.log)
        -> fetch full promotion info from DB (source of truth)
        -> send email
        -> record as notified (only after a successful send)

Run manually:
    python utils/promo_notifications.py

Cron (once per day):
    0 8 * * * cd /path/to/metziah && /path/to/venv/bin/python utils/promo_notifications.py
"""

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

sys.path.insert(0, str(PROJECT_DIR))

from chains.registry import CHAINS
from config import settings
from logging_config import setup_logging
from db import get_connection
from database.repository import get_nearby_store_ids, get_promotion_details
from utils.mailer import send_email


CHAIN = CHAINS["machsenei_hashuk"] # Machsanei Hashuk -- Phase 1 scope

LOG_DIR = PROJECT_DIR / "logs"
PROMO_CHANGES_LOG = LOG_DIR / (
    "promo_changes.test.log" if settings.ENV == "test" else "promo_changes.log"
)

NOTIFIED_FILE = PROJECT_DIR / "data" / "notified_promotions.log"

logger = setup_logging("promo_notifications")

_ADDED_LINE_RE = re.compile(r"PROMO ITEM ADDED (.+)")
_KV_RE = re.compile(
    r"(chain_id|store_id|promotion_id|group_id|item_code|name|discounted_price)="
    r"(.*?)(?=\s+\w+=|$)"
)

_REQUIRED_FIELDS = (
    "chain_id",
    "store_id",
    "promotion_id",
    "group_id",
    "item_code",
)


def build_digest_email(all_details: list[dict]) -> tuple[str, str]:
    """
    Builds one (subject, body) that just tells you how many new
    promotions showed up per store today -- no item-level detail.
    Check the DB/app for that.
    """

    total = len(all_details)

    counts: dict[str, int] = {}
    for details in all_details:
        store_label = f"{details['store_name']} (store {details['store_id']})"
        counts[store_label] = counts.get(store_label, 0) + 1

    subject = f"New supermarket promotions near you ({total})"

    lines = [
        f"{store}: {count} new promotion{'s' if count != 1 else ''}"
        for store, count in sorted(counts.items())
    ]

    body = "\n".join(lines) + "\n\nCheck the database/app for details."

    return subject, body


def parse_added_line(line: str) -> dict | None:
    """
    Extracts identity fields from a PROMO ITEM ADDED log line.

    name/discounted_price appear in the log too but are ignored here --
    the database is the source of truth for those (per spec).
    """
    match = _ADDED_LINE_RE.search(line)
    if not match:
        return None

    fields = dict(_KV_RE.findall(match.group(1)))

    if not all(f in fields for f in _REQUIRED_FIELDS):
        return None

    return {k: fields[k].strip() for k in _REQUIRED_FIELDS}


def read_added_events(log_path: Path) -> list[dict]:
    """
    Reads the full current promo_changes log and returns all
    PROMO ITEM ADDED events found in it.
    """
    if not log_path.exists():
        logger.info("Promo changes log not found: %s", log_path)
        return []

    events = []

    with log_path.open(encoding="utf-8") as f:
        for line in f:
            event = parse_added_line(line)
            if event:
                events.append(event)

    return events


def load_notified_keys() -> set[str]:
    if not NOTIFIED_FILE.exists():
        return set()

    with NOTIFIED_FILE.open(encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_notified(key: str) -> None:
    NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)

    with NOTIFIED_FILE.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


def event_key(event: dict) -> str:
    return "|".join(event[f] for f in _REQUIRED_FIELDS)


def run() -> None:
    if settings.USER_LAT is None or settings.USER_LON is None:
        logger.error("USER_LAT/USER_LON not configured -- aborting")
        return

    with get_connection() as conn:
        nearby_store_ids = get_nearby_store_ids(
            conn, CHAIN.chain_id, settings.USER_LAT, settings.USER_LON,
            settings.MAX_STORE_DISTANCE_KM,
        )

    logger.info("Found %d nearby store(s)", len(nearby_store_ids))

    if not nearby_store_ids:
        return

    nearby_store_ids = set(nearby_store_ids)
    events = read_added_events(PROMO_CHANGES_LOG)

    relevant_events = [
        e for e in events
        if e["chain_id"] == CHAIN.chain_id and e["store_id"] in nearby_store_ids
    ]

    logger.info("Found %d new relevant promotion(s)", len(relevant_events))

    if not relevant_events:
        return

    notified_keys = load_notified_keys()
    to_send = []  # list of (key, details)

    with get_connection() as conn:
        for event in relevant_events:
            key = event_key(event)

            if key in notified_keys:
                logger.info("Skipping already-notified promotion: %s", key)
                continue

            details = get_promotion_details(
                conn, event["chain_id"], event["store_id"],
                event["promotion_id"], event["group_id"], event["item_code"],
            )

            if details is None:
                logger.info("Promotion no longer exists, skipping: %s", key)
                continue

            to_send.append((key, details))

    if not to_send:
        return

    subject, body = build_digest_email([d for _, d in to_send])

    if send_email(subject, body):
        logger.info("Notification email sent for %d promotion(s)", len(to_send))
        for key, _ in to_send:
            mark_notified(key)
            notified_keys.add(key)
    else:
        logger.error("Notification email failed for %d promotion(s)", len(to_send))


if __name__ == "__main__":
    run()