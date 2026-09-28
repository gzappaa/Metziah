# tests/analytics/test_errors.py
from analytics.log_parsers import errors

SAMPLE_LOG = """\
2026-09-26 02:12:44,539 [ERROR] downloaders.common: FAILED downloading Price9999999999999-018-773-20260926-010000.gz
Traceback (most recent call last):
  File "common.py", line 161, in save_file_async
    content = await fetch_content()
httpx.HTTPStatusError: Client error '404 The specified blob does not exist.' for url 'https://x.blob.core.windows.net/price/foo.gz?sv=2014-02-14&sig=AAAA'
2026-09-26 02:12:44,600 [ERROR] downloaders.common: FAILED downloading Price9999999999999-019-773-20260926-010000.gz
Traceback (most recent call last):
  File "common.py", line 161, in save_file_async
    content = await fetch_content()
httpx.HTTPStatusError: Client error '404 The specified blob does not exist.' for url 'https://x.blob.core.windows.net/price/bar.gz?sv=2014-02-14&sig=BBBB'
2026-09-26 02:12:46,396 [ERROR] utils.prices.update_prices: Failed to load /path/foo.gz
Traceback (most recent call last):
  File "utils/prices/update_prices.py", line 601, in load_files
    file_had_prices = load_one_file(
psycopg.errors.ForeignKeyViolation: insert or update on table "prices_9999999999999" violates foreign key constraint
2026-09-26 02:20:00,000 [WARNING] root: not an error, should be ignored
"""


def test_errors_parse(tmp_path):
    path = tmp_path / "scheduler.log"
    path.write_text(SAMPLE_LOG, encoding="utf-8")
    data, txt_lines = errors.parse([path])

    assert data["total_errors"] == 3
    assert data["other_error_count"] == 1

    assert len(data["download_failures"]) == 1
    bucket = next(iter(data["download_failures"].values()))
    assert bucket["count"] == 2
    assert set(bucket["filenames"]) == {
        "Price9999999999999-018-773-20260926-010000.gz",
        "Price9999999999999-019-773-20260926-010000.gz",
    }

    fk_error = next(e for e in data["raw_errors"] if "ForeignKeyViolation" in e["message"])
    assert "load_files" in fk_error["message"]

    assert any("Full error log" in line for line in txt_lines)


def test_errors_no_error_lines_returns_zero(tmp_path):
    path = tmp_path / "scheduler.log"
    path.write_text("2026-09-26 02:00:00,000 [INFO] root: all fine\n", encoding="utf-8")
    data, _ = errors.parse([path])
    assert data["total_errors"] == 0
    assert data["download_failures"] == {}


def test_errors_reads_multiple_source_files(tmp_path):
    p1 = tmp_path / "scheduler.log"
    p1.write_text("2026-09-26 02:00:00,000 [ERROR] root: err one\n", encoding="utf-8")
    p2 = tmp_path / "price_changes.log"
    p2.write_text("2026-09-26 02:00:01,000 [ERROR] price_changes: err two\n", encoding="utf-8")
    data, _ = errors.parse([p1, p2])
    assert data["total_errors"] == 2
    sources = {e["source_file"] for e in data["raw_errors"]}
    assert sources == {"scheduler.log", "price_changes.log"}