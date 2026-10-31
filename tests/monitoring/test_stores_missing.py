
import csv
import json

import pytest

from monitoring import stores_missing as sm


# ---------------------------------------------------------------------------
# store_id_candidates
# ---------------------------------------------------------------------------

def test_store_id_candidates():
    assert sm.store_id_candidates("0007999") == [
        "0007999",
        "007999",
        "07999",
        "7999",
    ]


def test_store_id_candidates_without_leading_zeros():
    assert sm.store_id_candidates("1234") == ["1234"]


def test_store_id_candidates_all_zeros():
    assert sm.store_id_candidates("000") == ["000", "00", "0"]


def test_store_id_candidates_strips_whitespace():
    assert sm.store_id_candidates(" 00799 ") == ["00799", "0799", "799"]


# ---------------------------------------------------------------------------
# get_store_pairs
# ---------------------------------------------------------------------------

def test_get_store_pairs_from_list():
    data = [
        {"chain_id": "123", "store_id": "001"},
        {"chain_id": "123", "store_id": "002"},
        {"chain_id": "456", "store_id": "003"},
    ]

    assert sm.get_store_pairs(data) == {
        ("123", sm.normalize_store_id("001")),
        ("123", sm.normalize_store_id("002")),
        ("456", sm.normalize_store_id("003")),
    }


def test_get_store_pairs_from_stores_dict():
    data = {
        "stores": [
            {"chain_id": "123", "store_id": "001"},
        ]
    }

    assert sm.get_store_pairs(data) == {
        ("123", sm.normalize_store_id("001"))
    }


def test_get_store_pairs_from_values_dict():
    data = {
        "a": {"chain_id": "123", "store_id": "001"},
        "b": {"chain_id": "456", "store_id": "002"},
    }

    assert sm.get_store_pairs(data) == {
        ("123", sm.normalize_store_id("001")),
        ("456", sm.normalize_store_id("002")),
    }


@pytest.mark.parametrize("data", [None, "invalid", 123, []])
def test_get_store_pairs_invalid_or_empty_data(data):
    assert sm.get_store_pairs(data) == set()


def test_get_store_pairs_ignores_invalid_records():
    data = [
        None,
        "invalid",
        {},
        {"chain_id": "123"},
        {"store_id": "001"},
        {"chain_id": "", "store_id": "001"},
        {"chain_id": "123", "store_id": None},
        {"chain_id": "123", "store_id": "  "},
    ]

    assert sm.get_store_pairs(data) == set()


# ---------------------------------------------------------------------------
# load_chains
# ---------------------------------------------------------------------------

def test_load_chains_merges_files(tmp_path, monkeypatch):
    first = tmp_path / "chains.json"
    second = tmp_path / "chains_extra.json"

    first.write_text(
        json.dumps({"123": {"name": "First"}, "456": {"name": "Old"}}),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps({"456": {"name": "Updated"}, "789": {"name": "Extra"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "CHAINS_FILES", [first, second])

    assert sm.load_chains() == {
        "123": {"name": "First"},
        "456": {"name": "Updated"},
        "789": {"name": "Extra"},
    }


def test_load_chains_skips_missing_files(tmp_path, monkeypatch):
    existing = tmp_path / "chains.json"
    existing.write_text(
        json.dumps({"123": {"name": "First"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sm,
        "CHAINS_FILES",
        [tmp_path / "missing.json", existing],
    )

    assert sm.load_chains() == {"123": {"name": "First"}}


# ---------------------------------------------------------------------------
# extract_store_id_from_filename
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("filename", "chain_id", "expected"),
    [
        ("Price0000000000000-7999-202206130915.gz", "0000000000000", "7999"),
        ("Price12345-001-202601010000.gz", "12345", "001"),
        ("other-file.gz", "12345", ""),
        ("", "12345", ""),
        ("Price12345-001.gz", "12345", ""),
        ("Price12345-001-202601.gz", "", ""),
    ],
)
def test_extract_store_id_from_filename(filename, chain_id, expected):
    assert sm.extract_store_id_from_filename(filename, chain_id) == expected


# ---------------------------------------------------------------------------
# load_feed_data
# ---------------------------------------------------------------------------

def test_load_feed_data_groups_records_and_extracts_store_ids(
    tmp_path,
    monkeypatch,
):
    tracking_file = tmp_path / "file_tracking.csv"

    rows = [
        {
            "filename": "Price123-001-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "",
        },
        {
            "filename": "Price123-002-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "002",
        },
        {
            "filename": "Price456-003-202601010000.gz",
            "source": "Rami Levy",
            "chain_id": "456",
            "store_id": "003",
        },
        {
            "filename": "Stores123.json",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "999",
        },
        {
            "filename": "Price123-004-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "",
        },
        {
            "filename": "invalid.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "",
        },
        {
            "filename": "Price123-005-202601010000.gz",
            "source": "",
            "chain_id": "123",
            "store_id": "005",
        },
    ]

    with tracking_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(sm, "TRACKING_FILE", tracking_file)

    assert sm.load_feed_data() == {
        ("shufersal", "123"): {"001", "002", "004"},
        ("rami levy", "456"): {"003"},
    }


def test_load_feed_data_supports_utf8_bom(tmp_path, monkeypatch):
    tracking_file = tmp_path / "file_tracking.csv"

    with tracking_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["filename", "source", "chain_id", "store_id"],
        )
        writer.writeheader()
        writer.writerow({
            "filename": "Price123-001-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "001",
        })

    monkeypatch.setattr(sm, "TRACKING_FILE", tracking_file)

    assert sm.load_feed_data() == {
        ("shufersal", "123"): {"001"}
    }


# ---------------------------------------------------------------------------
# find_chain_anomalies
# ---------------------------------------------------------------------------

def test_find_chain_anomalies():
    feed_data = {
        ("shufersal", "123"),
        ("rami levy", "456"),
        ("unknown_source", "789"),
        ("shufersal", "999"),
    }

    chains = {
        "123": {"name_en_normalized": "shufersal"},
        "456": {"name_en_normalized": "victory"},
        "789": {"name_en_normalized": "unknown"},
    }

    assert sm.find_chain_anomalies(feed_data, chains) == [
        {
            "source": "rami levy",
            "chain_id": "456",
            "registered_owner": "victory",
        }
    ]


def test_find_chain_anomalies_ignores_missing_or_unknown_chains():
    feed_data = {
        ("source", "123"),
        ("source", "456"),
        ("source", "789"),
    }

    chains = {
        "123": {},
        "456": {"name_en_normalized": "unknown"},
    }

    assert sm.find_chain_anomalies(feed_data, chains) == []


# ---------------------------------------------------------------------------
# find_missing_stores
# ---------------------------------------------------------------------------

def test_find_missing_stores(tmp_path, monkeypatch):
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    stores_file = stores_dir / "shufersal.json"
    stores_file.write_text(
        json.dumps([
            {"chain_id": "123", "store_id": "001"},
            {"chain_id": "123", "store_id": "002"},
            {"chain_id": "456", "store_id": "003"},
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "STORES_DIR", stores_dir)

    assert sm.find_missing_stores(
        "shufersal",
        "123",
        {"001", "002", "004"},
    ) == ["004"]


def test_find_missing_stores_accepts_ids_with_leading_zeros(
    tmp_path,
    monkeypatch,
):
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    (stores_dir / "shufersal.json").write_text(
        json.dumps([
            {"chain_id": "123", "store_id": "7999"},
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "STORES_DIR", stores_dir)

    assert sm.find_missing_stores(
        "shufersal",
        "123",
        {"0007999"},
    ) == []


def test_find_missing_stores_requires_matching_chain_id(
    tmp_path,
    monkeypatch,
):
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    (stores_dir / "shufersal.json").write_text(
        json.dumps([
            {"chain_id": "456", "store_id": "001"},
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "STORES_DIR", stores_dir)

    assert sm.find_missing_stores(
        "shufersal",
        "123",
        {"001"},
    ) == ["001"]


def test_find_missing_stores_returns_all_when_file_missing(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(sm, "STORES_DIR", tmp_path)

    result = sm.find_missing_stores(
        "shufersal",
        "123",
        {"003", "001", "002"},
    )

    assert result == ["001", "002", "003"]
    assert "WARNING" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_generates_missing_stores_report(
    tmp_path,
    monkeypatch,
    capsys,
):
    tracking_file = tmp_path / "file_tracking.csv"
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()
    output_file = tmp_path / "output" / "missing.json"

    rows = [
        {
            "filename": "Price123-001-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "001",
        },
        {
            "filename": "Price123-002-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "002",
        },
    ]

    with tracking_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    (stores_dir / "shufersal.json").write_text(
        json.dumps([
            {"chain_id": "123", "store_id": "001"},
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(sm, "TRACKING_FILE", tracking_file)
    monkeypatch.setattr(sm, "STORES_DIR", stores_dir)
    monkeypatch.setattr(sm, "CHAINS_FILES", [])
    monkeypatch.setattr(sm, "OUTPUT_FILE", output_file)

    sm.main()

    assert json.loads(output_file.read_text(encoding="utf-8")) == {
        "shufersal:123": {
            "source": "shufersal",
            "chain_id": "123",
            "store_ids": ["002"],
        }
    }

    output = capsys.readouterr().out
    assert "Written:" in output
    assert "shufersal:123: 1 stores" in output


def test_main_missing_tracking_file(tmp_path, monkeypatch, capsys):
    tracking_file = tmp_path / "missing.csv"

    monkeypatch.setattr(sm, "TRACKING_FILE", tracking_file)

    sm.main()

    output = capsys.readouterr().out

    assert "WARNING" in output
    assert "Generate it first" in output
    assert not (tmp_path / "output").exists()


def test_main_reports_chain_anomalies_and_unknown_chains(
    tmp_path,
    monkeypatch,
    capsys,
):
    tracking_file = tmp_path / "file_tracking.csv"
    stores_dir = tmp_path / "stores"
    stores_dir.mkdir()

    output_file = tmp_path / "output" / "missing.json"

    rows = [
        {
            "filename": "Price123-001-202601010000.gz",
            "source": "Shufersal",
            "chain_id": "123",
            "store_id": "001",
        },
        {
            "filename": "Price456-002-202601010000.gz",
            "source": "Other",
            "chain_id": "456",
            "store_id": "002",
        },
    ]

    with tracking_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(sm, "TRACKING_FILE", tracking_file)
    monkeypatch.setattr(sm, "STORES_DIR", stores_dir)
    monkeypatch.setattr(sm, "CHAINS_FILES", [])
    monkeypatch.setattr(sm, "OUTPUT_FILE", output_file)

    monkeypatch.setattr(
        sm,
        "load_chains",
        lambda: {
            "123": {"name_en_normalized": "Different Owner"},
        },
    )

    sm.main()

    output = capsys.readouterr().out

    assert "CHAIN SOURCE ANOMALIES:" in output
    assert "shufersal publishes chain 123" in output
    assert "registered owner: different owner" in output
    assert "No chain found" in output

    report = json.loads(output_file.read_text(encoding="utf-8"))

    assert "shufersal:123" in report
    assert "other:456" in report
