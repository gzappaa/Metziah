# analytics/runner.py
"""
Runs the log parsers, writes their JSON+TXT reports under reports/{date}/,
then archives the source log files to logs/archives/{date}/.

Usage:
    python -m analytics.runner                      # run all four
    python -m analytics.runner --scheduler           # scheduler only
    python -m analytics.runner --prices --promos     # just these two
    python -m analytics.runner --scheduler --no-archive
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from analytics.log_parsers import common, scheduler, price_changes, promo_changes, errors

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

LOGS_DIR = BASE_DIR.parent / "logs"
REPORTS_DIR = BASE_DIR / "reports"
ARCHIVE_DIR = LOGS_DIR / "archives"

def _run_one(parser_module, report_name: str, paths: list[Path]) -> str | None:
    if not paths:
        print(f"[runner] no log files found for {report_name}, skipping")
        return None
    data, txt_lines = parser_module.parse(paths)
    run_date = data.get("run_date") or date.today().isoformat()
    common.write_report(report_name, run_date, data, txt_lines, REPORTS_DIR)
    print(f"[runner] wrote report_{report_name}.json/.txt for {run_date}")
    return run_date


def _archive(paths: list[Path], run_date: str) -> None:
    dest_dir = ARCHIVE_DIR / run_date
    dest_dir.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if p.exists():
            shutil.move(str(p), str(dest_dir / p.name))
            print(f"[runner] archived {p} -> {dest_dir / p.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheduler", action="store_true", help="run the scheduler.log parser")
    ap.add_argument("--prices", action="store_true", help="run the price_changes.log parser")
    ap.add_argument("--promos", action="store_true", help="run the promo_changes.log parser")
    ap.add_argument("--errors", action="store_true", help="run the errors parser (scans all logs used this run)")
    ap.add_argument("--no-archive", action="store_true", help="skip moving logs to archives/")
    args = ap.parse_args()

    # no flags at all => run everything, same as before
    run_all = not (args.scheduler or args.prices or args.promos or args.errors)

    scheduler_logs = common.find_rotated_logs(LOGS_DIR, "scheduler") if (run_all or args.scheduler or args.errors) else []
    price_logs = common.find_rotated_logs(LOGS_DIR, "price_changes") if (run_all or args.prices or args.errors) else []
    promo_logs = common.find_rotated_logs(LOGS_DIR, "promo_changes") if (run_all or args.promos or args.errors) else []

    run_dates: set[str] = set()
    archived_logs: list[Path] = []

    if run_all or args.scheduler:
        if (d := _run_one(scheduler, "scheduler", scheduler_logs)):
            run_dates.add(d)
        archived_logs += scheduler_logs

    if run_all or args.prices:
        if (d := _run_one(price_changes, "prices", price_logs)):
            run_dates.add(d)
        archived_logs += price_logs

    if run_all or args.promos:
        if (d := _run_one(promo_changes, "promos", promo_logs)):
            run_dates.add(d)
        archived_logs += promo_logs

    if run_all or args.errors:
        # errors.py scans whichever logs were fetched above for this run;
        # if run alone (--errors only), it still needs all three sources.
        error_source_logs = scheduler_logs + price_logs + promo_logs
        if (d := _run_one(errors, "errors", error_source_logs)):
            run_dates.add(d)
        # don't double-archive files already queued by scheduler/prices/promos above
        for p in error_source_logs:
            if p not in archived_logs:
                archived_logs.append(p)

    if not args.no_archive and archived_logs:
        run_date = sorted(run_dates)[-1] if run_dates else date.today().isoformat()
        _archive(archived_logs, run_date)
    elif not args.no_archive:
        print("[runner] nothing to archive")


if __name__ == "__main__":
    main()