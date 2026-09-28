import asyncio

from utils.file_tracking.load_file_tracking import (
    FILE_TRACKING_LOCK_ID,
    update_file_tracking,
)
from utils.file_tracking.data_enrichment.populate_file_sizes import (
    FILE_SIZE_LOCK_ID,
    main as populate_file_sizes,
)



def test_file_tracking_lock(conn, monkeypatch):
    async def fake_collect_all_files(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "utils.file_tracking.load_file_tracking.collect_all_files",
        fake_collect_all_files,
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock(%s)",
            (FILE_TRACKING_LOCK_ID,),
        )

    try:
        result = __import__("asyncio").run(
            update_file_tracking()
        )

        assert result == 0

    finally:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_unlock(%s)",
                (FILE_TRACKING_LOCK_ID,),
            )


def test_file_size_lock(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock(%s)",
            (FILE_SIZE_LOCK_ID,),
        )

    try:
        result = populate_file_sizes()

        assert result == 0

    finally:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_unlock(%s)",
                (FILE_SIZE_LOCK_ID,),
            )