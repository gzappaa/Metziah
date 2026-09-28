# tests/analytics/test_common.py
from datetime import datetime

from analytics.log_parsers import common

TEST_CHAINS = {"9999999999999": {"name_en_normalized": "test chain 9999"}}


def test_parse_timestamp():
    assert common.parse_timestamp("2026-09-26 02:06:02,380") == datetime(2026, 9, 26, 2, 6, 2, 380000)


def test_iter_log_entries_folds_traceback(tmp_path):
    text = (
        "2026-09-26 02:12:46,396 [ERROR] utils.prices.update_prices: Failed to load /path/foo.gz\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise ValueError\n"
        "ValueError: boom\n"
        "2026-09-26 02:12:47,000 [INFO] root: next entry\n"
    )
    path = tmp_path / "scheduler.log"
    path.write_text(text, encoding="utf-8")
    entries = list(common.iter_log_entries(path))

    assert len(entries) == 2
    assert entries[0].level == "ERROR"
    assert entries[0].message == "Failed to load /path/foo.gz"
    assert entries[0].extra_lines == [
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
        "    raise ValueError",
        "ValueError: boom",
    ]
    assert "ValueError: boom" in entries[0].full_message
    assert entries[1].message == "next entry"


def test_iter_log_entries_ignores_blank_lines_between(tmp_path):
    text = (
        "2026-09-26 02:06:02,380 [INFO] root: first\n"
        "\n"
        "2026-09-26 02:06:03,380 [INFO] root: second\n"
    )
    path = tmp_path / "scheduler.log"
    path.write_text(text, encoding="utf-8")
    entries = list(common.iter_log_entries(path))
    assert [e.message for e in entries] == ["first", "second"]
    assert entries[0].extra_lines == []


def test_find_rotated_logs_matches_expected_patterns(tmp_path):
    for name in ("scheduler.log", "scheduler.log.3", "scheduler.log.2026-09-26",
                 "scheduler.test.log", "price_changes.log", "scheduler.logfoo"):
        (tmp_path / name).write_text("x")

    found = {p.name for p in common.find_rotated_logs(tmp_path, "scheduler")}
    assert found == {"scheduler.log", "scheduler.log.3", "scheduler.log.2026-09-26"}


def test_find_rotated_logs_missing_dir_returns_empty(tmp_path):
    assert common.find_rotated_logs(tmp_path / "nope", "scheduler") == []


def test_format_timedelta():
    assert common.format_timedelta(45) == "45s"
    assert common.format_timedelta(125) == "2m 5s"
    assert common.format_timedelta(3725) == "1h 2m 5s"


def test_resolve_run_date_uses_earliest_entry_timestamp():
    entries = [
        common.LogEntry(datetime(2026, 9, 26, 2, 6, 2), "INFO", "root", "a"),
        common.LogEntry(datetime(2026, 9, 26, 3, 0, 0), "INFO", "root", "b"),
    ]
    assert common.resolve_run_date(entries) == "2026-09-26"


def test_resolve_run_date_empty_falls_back_to_today():
    result = common.resolve_run_date([])
    assert len(result) == 10 and result.count("-") == 2


def test_chain_name_resolves_and_falls_back(monkeypatch):
    monkeypatch.setattr(common, "_chain_cache", None)
    monkeypatch.setattr(common, "load_chains", lambda *a, **kw: TEST_CHAINS)
    assert common.chain_name("9999999999999") == "test chain 9999"
    assert common.chain_name("unknown_chain_id") == "unknown_chain_id"


def test_safe_db_call_success_and_failure():
    ok_result, err = common.safe_db_call(lambda: 42)
    assert ok_result == 42 and err is None

    def _boom():
        raise RuntimeError("db down")

    result, err = common.safe_db_call(_boom, default="fallback")
    assert result == "fallback"
    assert "db down" in err


def test_write_report_round_trips(tmp_path):
    data = {"a": 1, "nested": {"b": 2}}
    txt_lines = ["line one", "line two"]
    json_path, txt_path = common.write_report("scheduler", "2026-09-26", data, txt_lines, tmp_path)

    assert json_path == tmp_path / "2026-09-26" / "report_scheduler.json"
    assert txt_path == tmp_path / "2026-09-26" / "report_scheduler.txt"

    import json
    assert json.loads(json_path.read_text(encoding="utf-8")) == data
    assert txt_path.read_text(encoding="utf-8") == "line one\nline two\n"