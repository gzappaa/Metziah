from pathlib import Path
from unittest.mock import MagicMock, patch

from downloaders import scheduler


CHAIN_ID = "7290661400001"
SUB_CHAIN_ID = "003"
STORE_ID = "097"


def test_price_file_is_loaded_only_when_returned_by_file_tracking(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(scheduler, "FEEDS_DIR", tmp_path)

    tracked_file = (
        tmp_path
        / CHAIN_ID
        / SUB_CHAIN_ID
        / STORE_ID
        / "prices"
        / "tracked.gz"
    )

    untracked_file = (
        tmp_path
        / CHAIN_ID
        / SUB_CHAIN_ID
        / STORE_ID
        / "prices"
        / "untracked.gz"
    )

    tracked_file.parent.mkdir(parents=True)

    tracked_file.write_bytes(b"fake")
    untracked_file.write_bytes(b"fake")

    mock_conn = MagicMock()

    with (
        patch.object(
            scheduler,
            "download_prices",
            return_value=[],
        ),
        patch.object(
            scheduler,
            "get_connection",
        ) as mock_get_connection,
        patch.object(
            scheduler,
            "get_latest_downloaded_price_files",
        ) as mock_get_latest,
        patch.object(
            scheduler,
            "load_price_files",
            return_value=[tracked_file],
        ) as mock_load,
        patch.object(
            scheduler,
            "mark_loaded",
        ) as mock_mark_loaded,
    ):
        mock_get_connection.return_value.__enter__.return_value = mock_conn

        mock_get_latest.return_value = [
            (
                CHAIN_ID,
                SUB_CHAIN_ID,
                STORE_ID,
                "Price",
                "tracked.gz",
            )
        ]

        scheduler.run_prices_and_load()

    mock_load.assert_called_once()

    loaded_paths = mock_load.call_args.args[1]

    assert tracked_file in loaded_paths
    assert untracked_file not in loaded_paths

    mock_mark_loaded.assert_called_once_with(
        [tracked_file]
    )