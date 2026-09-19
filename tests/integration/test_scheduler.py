from datetime import date
from pathlib import Path

import pytest

from downloaders import scheduler


TEST_DATE = date(2026, 9, 17)


def insert_file(
    conn,
    *,
    chain_id,
    store_id,
    file_type,
    filename,
    file_date=TEST_DATE,
    downloaded=True,
    loaded=False,
    sub_chain_id="1",
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO file_tracking (
                chain_id,
                sub_chain_id,
                store_id,
                source,
                file_type,
                filename,
                file_date,
                downloaded,
                loaded
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                chain_id,
                sub_chain_id,
                store_id,
                "integration_test",
                file_type,
                filename,
                file_date,
                downloaded,
                loaded,
            ),
        )


def mark_loaded(conn, filenames):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE file_tracking
            SET loaded = true
            WHERE filename = ANY(%s)
            """,
            (filenames,),
        )


@pytest.fixture
def create_store(conn):
    def _create_store(
        chain_id,
        store_id,
        sub_chain_id="1",
    ):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chains (
                    chain_id,
                    name_he_normalized,
                    name_en_normalized
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (chain_id) DO NOTHING
                """,
                (
                    chain_id,
                    "test chain",
                    "test chain",
                ),
            )

            cur.execute(
                """
                INSERT INTO stores (
                    chain_id,
                    sub_chain_id,
                    store_id,
                    store_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (chain_id, store_id) DO NOTHING
                """,
                (
                    chain_id,
                    sub_chain_id,
                    store_id,
                    "Test Store",
                ),
            )

    return _create_store


@pytest.mark.integration
def test_scheduler_pricefull_then_price_with_real_db(
    conn,
    test_store,
    monkeypatch,
    tmp_path,
):
    """
    Price must wait for the same-day PriceFull to be loaded.

    This test verifies the real repository dependency:
        PriceFull loaded
            -> Price becomes eligible
    """

    chain_id = test_store["chain_id"]
    store_id = test_store["store_id_text"]
    sub_chain_id = "TEST_SUBCHAIN"

    pricefull_filename = (
        f"PriceFull{chain_id}-{sub_chain_id}-{store_id}.gz"
    )

    price_filename = (
        f"Price{chain_id}-{sub_chain_id}-{store_id}.gz"
    )

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        sub_chain_id=sub_chain_id,
        file_type="PriceFull",
        filename=pricefull_filename,
    )

    conn.commit()

    from database.repository import (
        get_downloaded_pricefull_files,
        get_downloaded_unloaded_price_files,
    )

    pricefull_pending = get_downloaded_pricefull_files(conn)

    assert len(pricefull_pending) == 1
    assert pricefull_pending[0][4] == pricefull_filename

    # No Price exists yet, so nothing should be eligible.
    assert get_downloaded_unloaded_price_files(conn) == []

    async def fake_download_prices(test):
        return []

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        fake_download_prices,
    )

    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    def fake_load_price_files(conn, files, feed_dir):
        filenames = [
            Path(path).name
            for path, *_ in files
        ]

        mark_loaded(conn, filenames)

        return [
            path
            for path, *_ in files
        ]

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        fake_load_price_files,
    )

    # Run scheduler with PriceFull only.
    scheduler.run_prices_and_load()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT loaded
            FROM file_tracking
            WHERE filename = %s
            """,
            (pricefull_filename,),
        )

        assert cur.fetchone() == (True,)

    # Now create the same-day Price file.
    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        sub_chain_id=sub_chain_id,
        file_type="Price",
        filename=price_filename,
    )

    conn.commit()

    eligible_prices = get_downloaded_unloaded_price_files(conn)

    assert len(eligible_prices) == 1
    assert eligible_prices[0][4] == price_filename

    # Cleanup.
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM file_tracking
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

        cur.execute(
            """
            DELETE FROM stores
            WHERE chain_id = %s
              AND store_id = %s
            """,
            (chain_id, store_id),
        )

    conn.commit()


@pytest.mark.integration
def test_pricefull_then_price_delta(
    conn,
    create_store,
    monkeypatch,
    tmp_path,
):
    """
    A normal Price feed is loaded with snapshot=False.

    Price must wait for the same-day PriceFull to be loaded.
    """

    chain_id = "7290058140886"
    store_id = "TEST_DELTA"

    create_store(chain_id, store_id)

    pricefull = "PriceFull-test-delta"
    price = "Price-test-delta"

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="PriceFull",
        filename=pricefull,
    )

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="Price",
        filename=price,
    )

    # Scheduler uses its own DB connection.
    conn.commit()

    async def fake_download_prices(test):
        return []

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        fake_download_prices,
    )

    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    loaded_calls = []

    def fake_load_price_files(conn, filepaths, feeds_dir):
        loaded_calls.extend(filepaths)

        filenames = [
            Path(filepath).name
            for filepath, _file_type, _snapshot in filepaths
        ]

        mark_loaded(conn, filenames)

        return [
            filepath
            for filepath, _file_type, _snapshot in filepaths
        ]

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        fake_load_price_files,
    )

    try:
        scheduler.run_prices_and_load()

        assert len(loaded_calls) == 2

        pricefull_call = next(
            call
            for call in loaded_calls
            if call[1] == "PriceFull"
        )

        price_call = next(
            call
            for call in loaded_calls
            if call[1] == "Price"
        )

        assert pricefull_call[2] is True
        assert price_call[2] is False

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

            cur.execute(
                """
                DELETE FROM stores
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

        conn.commit()


@pytest.mark.integration
def test_pricefull_then_price_laibcatalog_snapshot(
    conn,
    create_store,
    monkeypatch,
    tmp_path,
):
    """
    A Price feed from a Laibcatalog chain is loaded with
    snapshot=True.
    """

    chain_id = "7290661400001"
    store_id = "TEST_SNAPSHOT"

    create_store(chain_id, store_id)

    pricefull = "PriceFull-test-snapshot"
    price = "Price-test-snapshot"

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="PriceFull",
        filename=pricefull,
    )

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="Price",
        filename=price,
    )

    conn.commit()

    async def fake_download_prices(test):
        return []

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        fake_download_prices,
    )

    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    loaded_calls = []

    def fake_load_price_files(conn, filepaths, feeds_dir):
        loaded_calls.extend(filepaths)

        filenames = [
            Path(filepath).name
            for filepath, _file_type, _snapshot in filepaths
        ]

        mark_loaded(conn, filenames)

        return [
            filepath
            for filepath, _file_type, _snapshot in filepaths
        ]

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        fake_load_price_files,
    )

    try:
        scheduler.run_prices_and_load()

        assert len(loaded_calls) == 2

        pricefull_call = next(
            call
            for call in loaded_calls
            if call[1] == "PriceFull"
        )

        price_call = next(
            call
            for call in loaded_calls
            if call[1] == "Price"
        )

        assert pricefull_call[2] is True
        assert price_call[2] is True

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

            cur.execute(
                """
                DELETE FROM stores
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

        conn.commit()


@pytest.mark.integration
def test_pricefull_then_ignored_price_store(
    conn,
    create_store,
    monkeypatch,
    tmp_path,
):
    """
    An ignored Price store must never be passed to the loader.

    PriceFull is still loaded normally.
    """

    chain_id = "7290058108879"
    store_id = "003"

    create_store(chain_id, store_id)

    pricefull = "PriceFull-test-ignored"
    price = "Price-test-ignored"

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="PriceFull",
        filename=pricefull,
    )

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="Price",
        filename=price,
    )

    conn.commit()

    async def fake_download_prices(test):
        return []

    monkeypatch.setattr(
        scheduler,
        "download_prices",
        fake_download_prices,
    )

    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    loaded_calls = []

    def fake_load_price_files(conn, filepaths, feeds_dir):
        loaded_calls.extend(filepaths)

        filenames = [
            Path(filepath).name
            for filepath, _file_type, _snapshot in filepaths
        ]

        mark_loaded(conn, filenames)

        return [
            filepath
            for filepath, _file_type, _snapshot in filepaths
        ]

    monkeypatch.setattr(
        scheduler,
        "load_price_files",
        fake_load_price_files,
    )

    try:
        scheduler.run_prices_and_load()

        # PriceFull should have been loaded.
        assert any(
            call[1] == "PriceFull"
            for call in loaded_calls
        )

        # The ignored Price must never reach the loader.
        assert not any(
            call[1] == "Price"
            for call in loaded_calls
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT loaded
                FROM file_tracking
                WHERE filename = %s
                """,
                (price,),
            )

            assert cur.fetchone() == (False,)

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

            cur.execute(
                """
                DELETE FROM stores
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

        conn.commit()


@pytest.mark.integration
def test_promofull_then_promo(
    conn,
    create_store,
    monkeypatch,
    tmp_path,
):
    """
    A Promo file becomes eligible only after the same-day
    PromoFull has been loaded.
    """

    chain_id = "7290058140886"
    store_id = "TEST_PROMO"

    create_store(chain_id, store_id)

    promofull = "PromoFull-test"
    promo = "Promo-test"

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="PromoFull",
        filename=promofull,
    )

    insert_file(
        conn,
        chain_id=chain_id,
        store_id=store_id,
        file_type="Promo",
        filename=promo,
    )

    # Scheduler uses its own DB connection.
    conn.commit()

    async def fake_download_promofull(test):
        return []

    async def fake_download_promos(test):
        return []

    monkeypatch.setattr(
        scheduler,
        "download_promofull",
        fake_download_promofull,
    )

    monkeypatch.setattr(
        scheduler,
        "download_promos",
        fake_download_promos,
    )

    monkeypatch.setattr(
        scheduler,
        "FEEDS_DIR",
        tmp_path,
    )

    loaded_calls = []

    def fake_load_promo_files(conn, filepaths, feeds_dir):
        loaded_calls.extend(filepaths)

        filenames = [
            Path(filepath).name
            for filepath, *_ in filepaths
        ]

        mark_loaded(conn, filenames)

        return [
            filepath
            for filepath, *_ in filepaths
        ]

    monkeypatch.setattr(
        scheduler,
        "load_promo_files",
        fake_load_promo_files,
    )

    try:
        scheduler.run_promos_and_load()

        assert len(loaded_calls) == 2

        promofull_call = next(
            call
            for call in loaded_calls
            if call[1] == "PromoFull"
        )

        promo_call = next(
            call
            for call in loaded_calls
            if call[1] == "Promo"
        )

        assert Path(promofull_call[0]).name == promofull
        assert Path(promo_call[0]).name == promo

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT loaded
                FROM file_tracking
                WHERE filename = ANY(%s)
                ORDER BY filename
                """,
                ([promofull, promo],),
            )

            rows = cur.fetchall()

        assert rows == [(True,), (True,)]

    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM file_tracking
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

            cur.execute(
                """
                DELETE FROM stores
                WHERE chain_id = %s
                  AND store_id = %s
                """,
                (chain_id, store_id),
            )

        conn.commit()