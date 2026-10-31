import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.processing import generate_product_jsonl as generator


# ============================================================
# Helpers
# ============================================================

def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ============================================================
# Source directory normalization
# ============================================================

@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Tiv Taam", "tiv_taam"),
        ("  Super Yuda  ", "super_yuda"),
        ("Fresh-Market", "fresh-market"),
        ("Rami Levi!", "rami_levi"),
        ("", "unknown"),
        ("!!!", "unknown"),
    ],
)
def test_source_dir(source, expected):
    assert generator._source_dir(source) == expected


# ============================================================
# Regular product generation
# ============================================================

def test_generate_creates_jsonl_for_each_company(tmp_path):
    raw_dir = tmp_path / "raw"
    parsed_dir = tmp_path / "parsed"

    company_dir = raw_dir / "tiv taam"
    company_dir.mkdir(parents=True)

    (company_dir / "products.json").write_text("{}", encoding="utf-8")
    (company_dir / "another.json").write_text("{}", encoding="utf-8")

    products = {
        "products.json": [{"barcode": "123", "name": "Milk"}],
        "another.json": [{"barcode": "456", "name": "Bread"}],
    }

    def fake_iter_products(path, stats):
        yield from products[path.name]

    with patch.object(
        generator,
        "iter_products",
        side_effect=fake_iter_products,
    ):
        generator.generate(raw_dir, parsed_dir)

    output = parsed_dir / "tiv taam" / generator.OUTPUT_FILENAME
    records = read_jsonl(output)

    assert records == [
        {
            "company": "tiv taam",
            "source_file": "another.json",
            "barcode": "456",
            "name": "Bread",
        },
        {
            "company": "tiv taam",
            "source_file": "products.json",
            "barcode": "123",
            "name": "Milk",
        },
    ]


def test_generate_passes_stats_to_parser(tmp_path):
    raw_dir = tmp_path / "raw"
    parsed_dir = tmp_path / "parsed"

    company_dir = raw_dir / "company"
    company_dir.mkdir(parents=True)
    product_file = company_dir / "product.json"
    product_file.write_text("{}", encoding="utf-8")

    received_stats = {}

    def fake_iter_products(path, stats):
        received_stats.update(stats)
        stats["barcodes_recovered"] += 1
        yield {"barcode": "123"}

    with patch.object(
        generator,
        "iter_products",
        side_effect=fake_iter_products,
    ):
        generator.generate(raw_dir, parsed_dir)

    assert received_stats == {"barcodes_recovered": 0}


def test_generate_skips_invalid_files_and_continues(tmp_path, caplog):
    raw_dir = tmp_path / "raw"
    parsed_dir = tmp_path / "parsed"

    company_dir = raw_dir / "company"
    company_dir.mkdir(parents=True)

    (company_dir / "a.json").write_text("{}", encoding="utf-8")
    (company_dir / "b.json").write_text("{}", encoding="utf-8")

    def fake_iter_products(path, stats):
        if path.name == "a.json":
            raise ValueError("Invalid product")
        yield {"barcode": "123"}

    with (
        patch.object(
            generator,
            "iter_products",
            side_effect=fake_iter_products,
        ),
        caplog.at_level(logging.WARNING),
    ):
        generator.generate(raw_dir, parsed_dir)

    output = parsed_dir / "company" / generator.OUTPUT_FILENAME

    assert read_jsonl(output) == [
        {
            "company": "company",
            "source_file": "b.json",
            "barcode": "123",
        }
    ]
    assert "failed to parse" in caplog.text


def test_generate_raises_when_no_company_directories_exist(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    with pytest.raises(SystemExit, match="No sub-folders found"):
        generator.generate(raw_dir, tmp_path / "parsed")


# ============================================================
# Type 1 generation
# ============================================================

def test_generate_type1_groups_products_by_source(tmp_path):
    raw_dir = tmp_path / "type_1"
    parsed_dir = tmp_path / "parsed"

    raw_dir.mkdir()

    (raw_dir / "a.json").write_text("{}", encoding="utf-8")
    (raw_dir / "b.json").write_text("{}", encoding="utf-8")

    products = {
        "a.json": [
            {"source": "Tiv Taam", "name": "Milk"},
            {"source": "Super Yuda", "name": "Bread"},
        ],
        "b.json": [
            {"source": "Tiv Taam", "name": "Cheese"},
        ],
    }

    def fake_iter_products(path):
        yield from products[path.name]

    with patch.object(
        generator,
        "iter_type1_products",
        side_effect=fake_iter_products,
    ):
        generator.generate_type1(raw_dir, parsed_dir)

    tiv_output = (
        parsed_dir / "tiv_taam" / generator.TYPE1_OUTPUT_FILENAME
    )
    yuda_output = (
        parsed_dir / "super_yuda" / generator.TYPE1_OUTPUT_FILENAME
    )

    assert [p["name"] for p in read_jsonl(tiv_output)] == [
        "Milk",
        "Cheese",
    ]
    assert [p["name"] for p in read_jsonl(yuda_output)] == [
        "Bread",
    ]


def test_generate_type1_uses_unknown_for_missing_source(tmp_path):
    raw_dir = tmp_path / "type_1"
    parsed_dir = tmp_path / "parsed"
    raw_dir.mkdir()

    (raw_dir / "product.json").write_text("{}", encoding="utf-8")

    with patch.object(
        generator,
        "iter_type1_products",
        return_value=iter([{"name": "Milk"}]),
    ):
        generator.generate_type1(raw_dir, parsed_dir)

    output = parsed_dir / "unknown" / generator.TYPE1_OUTPUT_FILENAME

    assert read_jsonl(output) == [{"name": "Milk"}]


def test_generate_type1_raises_when_directory_missing(tmp_path):
    with pytest.raises(SystemExit, match="Input directory not found"):
        generator.generate_type1(
            tmp_path / "missing",
            tmp_path / "parsed",
        )


def test_generate_type1_raises_when_no_json_files(tmp_path):
    raw_dir = tmp_path / "type_1"
    raw_dir.mkdir()

    with pytest.raises(SystemExit, match="No JSON files found"):
        generator.generate_type1(raw_dir, tmp_path / "parsed")


def test_generate_type1_exits_if_a_file_fails(tmp_path, caplog):
    raw_dir = tmp_path / "type_1"
    parsed_dir = tmp_path / "parsed"
    raw_dir.mkdir()

    (raw_dir / "a.json").write_text("{}", encoding="utf-8")
    (raw_dir / "b.json").write_text("{}", encoding="utf-8")

    def fake_iter_products(path):
        if path.name == "a.json":
            raise ValueError("Invalid JSON")
        yield {"source": "Tiv Taam", "name": "Milk"}

    with (
        patch.object(
            generator,
            "iter_type1_products",
            side_effect=fake_iter_products,
        ),
        caplog.at_level(logging.WARNING),
        pytest.raises(SystemExit) as exc,
    ):
        generator.generate_type1(raw_dir, parsed_dir)

    assert exc.value.code == 1
    assert "failed to parse" in caplog.text

    output = parsed_dir / "tiv_taam" / generator.TYPE1_OUTPUT_FILENAME
    assert len(read_jsonl(output)) == 1


# ============================================================
# Type 2 generation
# ============================================================

def test_generate_type2_groups_products_by_parent_directory(tmp_path):
    raw_dir = tmp_path / "type_2"
    parsed_dir = tmp_path / "parsed"

    tiv_dir = raw_dir / "tiv taam"
    yuda_dir = raw_dir / "super yuda"

    tiv_dir.mkdir(parents=True)
    yuda_dir.mkdir(parents=True)

    (tiv_dir / "a.json").write_text("{}", encoding="utf-8")
    (yuda_dir / "b.json").write_text("{}", encoding="utf-8")

    def fake_iter_products(path):
        if path.name == "a.json":
            yield {"name": "Milk"}
        else:
            yield {"name": "Bread"}

    with patch.object(
        generator,
        "iter_type2_products",
        side_effect=fake_iter_products,
    ):
        generator.generate_type2(raw_dir, parsed_dir)

    tiv_output = (
        parsed_dir / "tiv_taam" / generator.TYPE2_OUTPUT_FILENAME
    )
    yuda_output = (
        parsed_dir / "super_yuda" / generator.TYPE2_OUTPUT_FILENAME
    )

    assert read_jsonl(tiv_output) == [
        {
            "company": "tiv_taam",
            "source": "tiv_taam",
            "source_file": "a.json",
            "name": "Milk",
        }
    ]

    assert read_jsonl(yuda_output) == [
        {
            "company": "super_yuda",
            "source": "super_yuda",
            "source_file": "b.json",
            "name": "Bread",
        }
    ]


def test_generate_type2_raises_when_directory_missing(tmp_path):
    with pytest.raises(SystemExit, match="Input directory not found"):
        generator.generate_type2(
            tmp_path / "missing",
            tmp_path / "parsed",
        )


def test_generate_type2_raises_when_no_json_files(tmp_path):
    raw_dir = tmp_path / "type_2"
    raw_dir.mkdir()

    with pytest.raises(SystemExit, match="No JSON files found"):
        generator.generate_type2(raw_dir, tmp_path / "parsed")


def test_generate_type2_exits_if_a_file_fails(tmp_path, caplog):
    raw_dir = tmp_path / "type_2"
    parsed_dir = tmp_path / "parsed"

    company_dir = raw_dir / "tiv taam"
    company_dir.mkdir(parents=True)

    (company_dir / "a.json").write_text("{}", encoding="utf-8")
    (company_dir / "b.json").write_text("{}", encoding="utf-8")

    def fake_iter_products(path):
        if path.name == "a.json":
            raise ValueError("Invalid product")
        yield {"name": "Milk"}

    with (
        patch.object(
            generator,
            "iter_type2_products",
            side_effect=fake_iter_products,
        ),
        caplog.at_level(logging.WARNING),
        pytest.raises(SystemExit) as exc,
    ):
        generator.generate_type2(raw_dir, parsed_dir)

    assert exc.value.code == 1
    assert "failed to parse" in caplog.text

    output = parsed_dir / "tiv_taam" / generator.TYPE2_OUTPUT_FILENAME
    assert len(read_jsonl(output)) == 1


# ============================================================
# CLI
# ============================================================

@pytest.mark.parametrize(
    "args",
    [
        ["--type1", "--type2"],
        ["--type1", "--all"],
        ["--type2", "--all"],
    ],
)
def test_main_rejects_conflicting_modes(args):
    with (
        patch("sys.argv", ["generate_parsed_products.py", *args]),
        pytest.raises(SystemExit) as exc,
    ):
        generator.main()

    assert exc.value.code == 2


def test_main_defaults_to_regular_generation(tmp_path):
    raw_dir = tmp_path / "raw"
    parsed_dir = tmp_path / "parsed"

    with (
        patch(
            "sys.argv",
            [
                "generate_parsed_products.py",
                "--raw-dir",
                str(raw_dir),
                "--parsed-dir",
                str(parsed_dir),
            ],
        ),
        patch.object(generator, "generate") as generate,
        patch.object(generator, "setup_general_logging", create=True),
    ):
        generator.main()

    generate.assert_called_once_with(raw_dir, parsed_dir)


def test_main_runs_type1_only():
    with (
        patch(
            "sys.argv",
            ["generate_parsed_products.py", "--type1"],
        ),
        patch.object(generator, "generate_type1") as generate_type1,
    ):
        generator.main()

    generate_type1.assert_called_once_with(
        generator.DEFAULT_TYPE1_RAW_DIR,
        generator.DEFAULT_PARSED_DIR,
    )


def test_main_runs_type2_only():
    with (
        patch(
            "sys.argv",
            ["generate_parsed_products.py", "--type2"],
        ),
        patch.object(generator, "generate_type2") as generate_type2,
    ):
        generator.main()

    generate_type2.assert_called_once_with(
        generator.DEFAULT_TYPE2_RAW_DIR,
        generator.DEFAULT_PARSED_DIR,
    )


def test_main_runs_all_modes():
    with (
        patch(
            "sys.argv",
            ["generate_parsed_products.py", "--all"],
        ),
        patch.object(generator, "generate") as generate,
        patch.object(generator, "generate_type1") as generate_type1,
        patch.object(generator, "generate_type2") as generate_type2,
    ):
        generator.main()

    generate.assert_called_once_with(
        generator.DEFAULT_RAW_DIR,
        generator.DEFAULT_PARSED_DIR,
    )
    generate_type1.assert_called_once_with(
        generator.DEFAULT_TYPE1_RAW_DIR,
        generator.DEFAULT_PARSED_DIR,
    )
    generate_type2.assert_called_once_with(
        generator.DEFAULT_TYPE2_RAW_DIR,
        generator.DEFAULT_PARSED_DIR,
    )