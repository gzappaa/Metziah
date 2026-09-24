"""
Populates missing file sizes in `file_tracking` from files already
downloaded under data/feeds/.

The script does not make any HTTP requests.

Only rows with:
    downloaded = TRUE
    file_size IS NULL

are processed.

The script is safe to run repeatedly.
"""

import logging
from pathlib import Path

import psycopg

from config import settings


BASE_DIR = Path(__file__).resolve().parents[3]
FEEDS_DIR = BASE_DIR / "data" / "feeds"

FILE_TYPE_DIRECTORIES = {
    "PriceFull": "pricesfull",
    "Price": "prices",
    "PromoFull": "promosfull",
    "Promo": "promos",
    "Stores": "stores",
}

FILE_SIZE_LOCK_ID = 847292

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
        dbname=settings.PGDATABASE,
    )


def get_missing_file_sizes(conn):
    """Return downloaded file_tracking rows that have no recorded size."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                chain_id,
                store_id,
                file_type,
                filename
            FROM file_tracking
            WHERE downloaded = TRUE
              AND file_size IS NULL
            ORDER BY id
            """
        )
        return cur.fetchall()


def get_file_path(chain_id, store_id, file_type, filename):
    """Build the expected local path for a tracked file."""
    directory = FILE_TYPE_DIRECTORIES.get(file_type)

    if directory is None:
        raise ValueError(f"Unsupported file type: {file_type}")

    chain_dir = FEEDS_DIR / str(chain_id)

    if file_type == "Stores":
        return chain_dir / directory / filename

    return chain_dir / str(store_id) / directory / filename


def update_file_size(conn, file_tracking_id, file_size):
    """Store the local file size in file_tracking."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE file_tracking
            SET
                file_size = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (file_size, file_tracking_id),
        )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Scanning file_tracking for missing file sizes")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (FILE_SIZE_LOCK_ID,),
            )

            if not cur.fetchone()[0]:
                logger.info(
                    "File size population is already running; skipping"
                )
                return 0

            try:
                rows = get_missing_file_sizes(conn)

                logger.info(
                    "Found %d file(s) with missing file_size",
                    len(rows),
                )

                updated = 0
                missing = 0

                for (
                    file_tracking_id,
                    chain_id,
                    store_id,
                    file_type,
                    filename,
                ) in rows:
                    path = get_file_path(
                        chain_id=chain_id,
                        store_id=store_id,
                        file_type=file_type,
                        filename=filename,
                    )

                    if not path.is_file():
                        logger.warning(
                            "File not found: id=%s path=%s",
                            file_tracking_id,
                            path,
                        )
                        missing += 1
                        continue

                    file_size = path.stat().st_size

                    update_file_size(
                        conn=conn,
                        file_tracking_id=file_tracking_id,
                        file_size=file_size,
                    )

                    updated += 1

                    logger.debug(
                        "Updated file_size: id=%s size=%d filename=%s",
                        file_tracking_id,
                        file_size,
                        filename,
                    )

                conn.commit()

            finally:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (FILE_SIZE_LOCK_ID,),
                )

    logger.info(
        "Finished: updated=%d missing=%d",
        updated,
        missing,
    )


if __name__ == "__main__":
    main()