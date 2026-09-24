# tests/monitoring/test_chains_missing.py

import json

import monitoring.chains_missing as chains_missing


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )


def read_json(path):
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_build_filename_chains_known_and_unknown():
    chains = {
        "1111111111111": {
            "name_en_normalized": "KnownChain"
        }
    }

    records = [
        {
            "source": "KnownChain",
            "chain_id": "1111111111111",
            "store_id": "001",
        },
        {
            "source": "KnownChain",
            "chain_id": "2222222222222",
            "store_id": "002",
        },
    ]

    result = chains_missing.build_filename_chains(
        records,
        chains,
    )

    assert result == {
        "KnownChain": {
            "chain_ids": [
                "1111111111111",
                "2222222222222",
            ],
            "chain_names": {
                "1111111111111": "KnownChain",
            },
            "unknown_chain_ids": [
                "2222222222222",
            ],
            "unknown_store_ids": {
                "2222222222222": ["002"],
            },
            "placeholder_chain_ids": [],
        }
    }


def test_build_filename_chains_placeholder():
    result = chains_missing.build_filename_chains(
        [
            {
                "source": "Test",
                "chain_id": "0000000000000",
                "store_id": "001",
            }
        ],
        {},
    )

    assert result["Test"]["placeholder_chain_ids"] == [
        "0000000000000"
    ]

    assert result["Test"]["unknown_chain_ids"] == []


def test_build_filename_chains_ignores_missing_source_or_chain():
    records = [
        {
            "source": "",
            "chain_id": "1111111111111",
            "store_id": "001",
        },
        {
            "source": "Test",
            "chain_id": "",
            "store_id": "002",
        },
    ]

    assert chains_missing.build_filename_chains(
        records,
        {},
    ) == {}


def test_build_chains_extra_copies_known_chain():
    chains = {
        "1111111111111": {
            "Chain_name_store_file": "Known",
            "Chain_name_gov_page": "Known Gov",
            "name_he_normalized": "known",
            "name_en_normalized": "KnownChain",
            "web_site": "https://example.com",
            "publishing_in": "KnownChain",
            "client": "client",
        }
    }

    filename_chains = {
        "KnownChain": {
            "chain_ids": [
                "1111111111111",
                "2222222222222",
            ],
            "unknown_chain_ids": [
                "2222222222222",
            ],
            "unknown_store_ids": {
                "2222222222222": ["003"],
            },
            "chain_names": {
                "1111111111111": "KnownChain",
            },
            "placeholder_chain_ids": [],
        }
    }

    result = chains_missing.build_chains_extra(
        filename_chains,
        chains,
    )

    assert result["2222222222222"] == chains[
        "1111111111111"
    ]

    assert result["0000000000000"] == (
        chains_missing.PLACEHOLDER_CHAIN
    )


def test_build_chains_extra_does_not_copy_when_multiple_known_chains():
    chains = {
        "1111111111111": {"name_en_normalized": "Chain1"},
        "2222222222222": {"name_en_normalized": "Chain2"},
    }

    filename_chains = {
        "Source": {
            "chain_ids": [
                "1111111111111",
                "2222222222222",
                "3333333333333",
            ],
            "unknown_chain_ids": [
                "3333333333333",
            ],
        }
    }

    result = chains_missing.build_chains_extra(
        filename_chains,
        chains,
    )

    assert "3333333333333" not in result
    assert "0000000000000" in result


def test_build_chains_extra_does_not_copy_when_no_known_chain():
    filename_chains = {
        "Source": {
            "chain_ids": [
                "1111111111111",
            ],
            "unknown_chain_ids": [
                "1111111111111",
            ],
        }
    }

    result = chains_missing.build_chains_extra(
        filename_chains,
        {},
    )

    assert "1111111111111" not in result


def test_build_chains_extra_multiple_unknowns():
    chains = {
        "1111111111111": {
            "name_en_normalized": "Known"
        }
    }

    filename_chains = {
        "Known": {
            "chain_ids": [
                "1111111111111",
                "2222222222222",
                "3333333333333",
            ],
            "unknown_chain_ids": [
                "2222222222222",
                "3333333333333",
            ],
        }
    }

    result = chains_missing.build_chains_extra(
        filename_chains,
        chains,
    )

    assert result["2222222222222"] == chains[
        "1111111111111"
    ]
    assert result["3333333333333"] == chains[
        "1111111111111"
    ]


def test_build_chains_extra_no_unknowns():
    chains = {
        "1111111111111": {
            "name_en_normalized": "Known"
        }
    }

    filename_chains = {
        "Known": {
            "chain_ids": ["1111111111111"],
            "unknown_chain_ids": [],
        }
    }

    result = chains_missing.build_chains_extra(
        filename_chains,
        chains,
    )

    assert result == {
        "0000000000000": chains_missing.PLACEHOLDER_CHAIN
    }


def test_load_previous_filename_chains_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chains_missing,
        "OUTPUT_FILE",
        tmp_path / "missing.json",
    )

    assert (
        chains_missing.load_previous_filename_chains()
        == {}
    )


def test_load_previous_filename_chains(tmp_path, monkeypatch):
    path = tmp_path / "filename_chains.json"

    data = {"Source": {"chain_ids": ["1111111111111"]}}

    write_json(path, data)

    monkeypatch.setattr(
        chains_missing,
        "OUTPUT_FILE",
        path,
    )

    assert (
        chains_missing.load_previous_filename_chains()
        == data
    )


def test_write_json(tmp_path):
    path = tmp_path / "nested" / "data.json"
    data = {"test": ["value"]}

    chains_missing.write_json(path, data)

    assert read_json(path) == data
    assert path.read_text(encoding="utf-8").endswith(
        "\n"
    )


def test_main_writes_both_files(tmp_path, monkeypatch):
    chains_file = tmp_path / "chains.json"
    tracking_file = tmp_path / "file_tracking.csv"
    output_file = tmp_path / "filename_chains.json"
    extra_file = tmp_path / "chains_extra.json"

    write_json(
        chains_file,
        {
            "1111111111111": {
                "name_en_normalized": "KnownChain",
                "metadata": "keep",
            }
        },
    )

    tracking_file.write_text(
        "source,chain_id,store_id\n"
        "KnownChain,1111111111111,001\n"
        "KnownChain,2222222222222,002\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        chains_missing,
        "CHAINS_FILE",
        chains_file,
    )
    monkeypatch.setattr(
        chains_missing,
        "FILE_TRACKING_FILE",
        tracking_file,
    )
    monkeypatch.setattr(
        chains_missing,
        "OUTPUT_FILE",
        output_file,
    )
    monkeypatch.setattr(
        chains_missing,
        "CHAINS_EXTRA_FILE",
        extra_file,
    )

    chains_missing.main()

    filename_chains = read_json(output_file)
    chains_extra = read_json(extra_file)

    assert filename_chains[
        "KnownChain"
    ]["unknown_chain_ids"] == [
        "2222222222222"
    ]

    assert chains_extra[
        "2222222222222"
    ] == {
        "name_en_normalized": "KnownChain",
        "metadata": "keep",
    }

    assert "0000000000000" in chains_extra