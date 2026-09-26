# analytics/log_parsers/common.py
"""
Shared helpers for the log-parser scripts: log-line parsing, log-entry
iteration (with traceback/continuation-line folding), datetime helpers,
chain-name resolution, dual JSON+TXT report writing, and the couple of
DB lookups that price_changes.py / promo_changes.py both need.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
from db import get_connection

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"\[(?P<level>[A-Z]+)\] "
    r"(?P<logger>[\w.]+): "
    r"(?P<message>.*)$"
)

TS_FORMAT = "%Y-%m-%d %H:%M:%S,%f"


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    logger: str
    message: str  # first line only
    extra_lines: list[str] = field(default_factory=list)  # traceback / wrapped lines
    source_file: str = ""

    @property
    def full_message(self) -> str:
        if not self.extra_lines:
            return self.message
        return self.message + "\n" + "\n".join(self.extra_lines)


def parse_timestamp(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FORMAT)


def iter_log_entries(path: Path) -> Iterator[LogEntry]:
    """
    Yields one LogEntry per top-level log line, folding any following lines
    that do NOT match LOG_LINE_RE (tracebacks, wrapped messages) into that
    entry's extra_lines. This is what lets errors.py capture full tracebacks
    verbatim while everything else just sees a one-line message.
    """
    current: Optional[LogEntry] = None
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            m = LOG_LINE_RE.match(line)
            if m:
                if current is not None:
                    yield current
                current = LogEntry(
                    timestamp=parse_timestamp(m.group("ts")),
                    level=m.group("level"),
                    logger=m.group("logger"),
                    message=m.group("message"),
                    source_file=path.name,
                )
            else:
                if current is not None and line != "":
                    current.extra_lines.append(line)
    if current is not None:
        yield current


def find_rotated_logs(logs_dir: Path, base_name: str) -> list[Path]:
    """
    Matches `{base_name}.log` and `{base_name}.log.<digits>` (current test
    rotation) plus `{base_name}.log.<YYYY-MM-DD>` (future rotation scheme).
    Explicitly excludes `{base_name}.test.log`.
    """
    pattern = re.compile(
        rf"^{re.escape(base_name)}\.log(\.\d+|\.\d{{4}}-\d{{2}}-\d{{2}})?$"
    )
    if not logs_dir.exists():
        return []
    return sorted(
        p for p in logs_dir.glob(f"{base_name}*")
        if p.is_file() and pattern.match(p.name)
    )


def format_timedelta(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def earliest_timestamp(entries: list[LogEntry]) -> Optional[datetime]:
    return min((e.timestamp for e in entries), default=None)


def resolve_run_date(entries: list[LogEntry]) -> str:
    """Uses the date embedded in the log itself so the report reflects the
    log's actual date, not the day the parser happens to run."""
    ts = earliest_timestamp(entries)
    return (ts.date() if ts else datetime.now().date()).isoformat()


# ---------------------------------------------------------------------------
# Chain name resolution
# ---------------------------------------------------------------------------

_chain_cache: dict[str, dict] | None = None


def load_chains(
    chains_path: Path = Path("data/reference/chains.json"),
    chains_extra_path: Path = Path("data/reference/chains_extra.json"),
) -> dict[str, dict]:
    global _chain_cache
    if _chain_cache is not None:
        return _chain_cache

    merged: dict[str, dict] = {}
    for p in (chains_path, chains_extra_path):
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for chain_id, record in data.items():
                merged.setdefault(chain_id, {}).update(record)

    _chain_cache = merged
    return merged


def chain_name(chain_id: str, chains: Optional[dict[str, dict]] = None) -> str:
    """Best-effort English normalized chain name; falls back to the raw id."""
    chains = chains if chains is not None else load_chains()
    record = chains.get(chain_id)
    if not record:
        return chain_id
    return record.get("name_en_normalized") or chain_id


# ---------------------------------------------------------------------------
# Shared DB lookups (price_changes.py + promo_changes.py both need these)
# ---------------------------------------------------------------------------

def safe_db_call(fn, *args, default=None, **kwargs):
    """
    Runs a DB-dependent callable, swallowing connection/query errors so a
    down DB doesn't crash the whole report run — callers get `default` back
    plus the error string, and can note "db_unavailable" in the report
    instead of silently skipping checks (silent gaps are the thing to avoid).
    """
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 - deliberately broad, best-effort report
        return default, str(exc)


def fetch_universal_product_codes(item_codes: set[str]) -> set[str]:
    """Which of these item_codes are real barcodes in `products` (i.e. safe
    to compare across chains, vs. chain-internal store_products codes)."""
    if not item_codes:
        return set()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_code FROM products WHERE item_code = ANY(%s)",
                (list(item_codes),),
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def fetch_store_counts(chain_ids: set[str]) -> dict[str, int]:
    """Total store count per chain, for %-of-chain-affected calculations."""
    if not chain_ids:
        return {}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chain_id, COUNT(*) FROM stores WHERE chain_id = ANY(%s) GROUP BY chain_id",
                (list(chain_ids),),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_report(
    name: str,
    date_str: str,
    data: dict,
    txt_lines: list[str],
    reports_dir: Path = Path("reports"),
) -> tuple[Path, Path]:
    """Writes reports/{date_str}/report_{name}.json and .txt"""
    out_dir = reports_dir / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"report_{name}.json"
    txt_path = out_dir / f"report_{name}.txt"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    with txt_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines) + "\n")

    return json_path, txt_path