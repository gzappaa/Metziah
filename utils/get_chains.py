# utils/chain.py

import json
import logging

from pathlib import Path

from utils.stores.get_stores import (
    FEEDS_DIR,
    find_stores_file,
    read_xml_content,
    parse_stores_xml,
)
from logging_config import setup_general_logging


# Project root
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

CHAINS_FILE = DATA_DIR / "chains.json"


setup_general_logging()

logger = logging.getLogger(__name__)


def load_existing() -> dict:
    if not CHAINS_FILE.exists():
        return {}

    with open(
        CHAINS_FILE,
        encoding="utf-8",
    ) as f:
        return json.load(f)


def main():

    chains = {}

    for chain_dir in sorted(FEEDS_DIR.iterdir()):

        if not chain_dir.is_dir():
            continue

        chain_id_from_path = chain_dir.name

        stores_file = find_stores_file(chain_dir)

        if stores_file is None:
            logger.warning(
                "No stores file found for %s",
                chain_id_from_path,
            )
            continue

        logger.info(
            "Parsing %s",
            stores_file.name,
        )

        try:
            xml_content = read_xml_content(
                stores_file
            )

            chain_info, _ = parse_stores_xml(
                xml_content,
                chain_id_from_path,
            )

        except Exception:
            logger.exception(
                "Failed to parse %s",
                stores_file,
            )
            continue

        chain_id = chain_info["chain_id"]
        chain_name = chain_info["chain_name"]

        if not chain_name:
            logger.warning(
                "Missing ChainName: %s",
                chain_id,
            )

        chains[chain_id] = {
            "name": chain_name,
        }

    with open(
        CHAINS_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            chains,
            f,
            ensure_ascii=False,
            indent=4,
        )

    logger.info(
        "Saved %d chains to %s",
        len(chains),
        CHAINS_FILE,
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        logger.exception(
            "Chain registry generation crashed"
        )
        raise