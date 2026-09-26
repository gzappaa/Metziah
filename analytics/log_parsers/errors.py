# analytics/log_parsers/errors.py
"""
Scans scheduler.log*, price_changes.log and promo_changes.log for
ERROR-level entries, keeping the full message + traceback verbatim, and
additionally groups the very common "downloaders.common: FAILED
downloading <file>" bursts so 200 failures over one root cause read as
one line, not 200 — everything else still appears in full below it.
"""

from __future__ import annotations

import re
from pathlib import Path

from analytics.log_parsers import common
from analytics.log_parsers.common import LogEntry

FAILED_DOWNLOAD_RE = re.compile(r"^FAILED downloading (?P<filename>\S+)$")


def _classify_download_failure(full_message: str) -> str:
    lines = [l for l in full_message.splitlines() if l.strip()]
    if not lines:
        return "unknown"

    last = lines[-1]
    m = re.match(r"^([\w.]+Error): (.+)$", last)
    if m:
        exc_type, exc_msg = m.groups()

        # Remove URLs because they identify the individual file,
        # not the underlying failure reason.
        exc_msg = re.sub(r"\s+for url '.*?'", "", exc_msg)

        return f"{exc_type}: {exc_msg[:150]}"

    return last[:150]


def parse(paths: list[Path]) -> tuple[dict, list[str]]:
    entries: list[LogEntry] = []
    for p in paths:
        entries.extend(common.iter_log_entries(p))
    entries.sort(key=lambda e: e.timestamp)

    raw_errors = []
    download_failures: dict[str, dict] = {}
    other_error_count = 0

    for e in entries:
        if e.level != "ERROR":
            continue
        raw_errors.append({
            "timestamp": e.timestamp.isoformat(),
            "logger": e.logger,
            "source_file": e.source_file,
            "message": e.full_message,
        })

        m = FAILED_DOWNLOAD_RE.match(e.message)
        if e.logger == "downloaders.common" and m:
            reason = _classify_download_failure(e.full_message)
            bucket = download_failures.setdefault(reason, {"count": 0, "filenames": []})
            bucket["count"] += 1
            bucket["filenames"].append(m.group("filename"))
        else:
            other_error_count += 1

    data = {
        "run_date": common.resolve_run_date(entries),
        "total_errors": len(raw_errors),
        "download_failures": download_failures,
        "other_error_count": other_error_count,
        "raw_errors": raw_errors,
    }
    return data, _render_txt(data)


def _render_txt(data: dict) -> list[str]:
    lines = ["=== Errors report ===", f"Run date: {data['run_date']}",
             f"Total ERROR entries: {data['total_errors']}", ""]

    if data["download_failures"]:
        lines.append("-- Grouped download failures (downloaders.common) --")
        for reason, bucket in sorted(data["download_failures"].items(), key=lambda kv: -kv[1]["count"]):
            lines.append(f"[{bucket['count']}x] {reason}")
            for fn in bucket["filenames"][:10]:
                lines.append(f"    - {fn}")
            if len(bucket["filenames"]) > 10:
                lines.append(f"    ... and {len(bucket['filenames']) - 10} more")
        lines.append("")

    lines.append("-- Full error log (verbatim) --")
    for err in data["raw_errors"]:
        lines.append(f"[{err['timestamp']}] {err['logger']} ({err['source_file']})")
        lines.append(err["message"])
        lines.append("")

    return lines