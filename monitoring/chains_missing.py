'''monitoring/chains_missing.py'''
'''
WHY THIS SCRIPT EXISTS
======================

A publisher/source does not necessarily correspond to exactly one
chain_id.

For example, City Market was found publishing files for TWO different
chain IDs under the same publisher/source. This means we cannot safely
assume:

    source -> chain_id

is always a one-to-one relationship.

This matters because chain_id is part of the identity of stores and
feed files in the database. Assuming that every source has only one
chain can cause files to be assigned to the wrong chain, stores to be
created under the wrong chain, and file_tracking/load operations to
fail or become inconsistent.

This script analyzes the file_tracking report and:

    - records every chain_id observed for each source
    - identifies unknown chain IDs
    - identifies stores associated with unknown chains
    - detects sources publishing multiple chain IDs
    - detects source/chain mismatches against chains.json
    - tracks changes between runs
    - generates chains_extra.json when an unknown chain can be safely
      associated with exactly one known chain for that source

Running this regularly is important before adding or updating chains.
Unexpected publisher/chain relationships can otherwise cause problems
throughout the database loading pipeline.

In particular, do not assume that a source name uniquely identifies a
chain. The actual chain_id from the feed must be inspected and
validated.
'''

import csv
import json
import logging
from collections import defaultdict
from pathlib import Path

from config import settings
from logging_config import setup_general_logging


setup_general_logging()
logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parents[1]

FILE_TRACKING_FILE = (
    BASE_DIR
    / "data"
    / "reference"
    / "file_tracking.csv"
)

CHAINS_FILE = (
    BASE_DIR
    / "data"
    / "reference"
    / "chains.json"
)

CHAINS_EXTRA_FILE = (
    BASE_DIR
    / "data"
    / "reference"
    / "chains_extra.json"
)

OUTPUT_FILE = (
    BASE_DIR
    / "monitoring"
    / "data"
    / "filename_chains.json"
)

PLACEHOLDER_CHAIN_IDS = {
    "0000000000000",
}

PLACEHOLDER_CHAIN = {
    "Chain_name_store_file": "unknown",
    "Chain_name_gov_page": "unknown",
    "name_he_normalized": "unknown",
    "name_en_normalized": "unknown",
    "web_site": "unknown",
    "publishing_in": "unknown",
    "client": "unknown",
}


def load_chains() -> dict:
    with CHAINS_FILE.open(
        encoding="utf-8",
    ) as file:
        return json.load(file)


def load_file_tracking() -> list[dict]:
    with FILE_TRACKING_FILE.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(
            csv.DictReader(file)
        )


def load_previous_filename_chains() -> dict:
    if not OUTPUT_FILE.exists():
        return {}

    with OUTPUT_FILE.open(
        encoding="utf-8",
    ) as file:
        return json.load(file)


def build_filename_chains(
    records: list[dict],
    chains: dict,
) -> dict:
    observed = defaultdict(set)

    for record in records:
        source = record.get("source")
        chain_id = record.get("chain_id")

        if not source or not chain_id:
            continue

        observed[source].add(chain_id)

    result = {}

    for source in sorted(observed):
        chain_ids = sorted(
            observed[source]
        )

        source_data = {
            "chain_ids": chain_ids,
            "chain_names": {},
            "unknown_chain_ids": [],
            "unknown_store_ids": {},
            "placeholder_chain_ids": [],
        }

        for chain_id in chain_ids:
            if chain_id in PLACEHOLDER_CHAIN_IDS:
                source_data[
                    "placeholder_chain_ids"
                ].append(chain_id)
                continue

            chain = chains.get(chain_id)

            if chain is None:
                source_data[
                    "unknown_chain_ids"
                ].append(chain_id)

                store_ids = sorted({
                    record["store_id"]
                    for record in records
                    if (
                        record.get("source") == source
                        and record.get("chain_id") == chain_id
                        and record.get("store_id")
                    )
                })

                if store_ids:
                    source_data[
                        "unknown_store_ids"
                    ][chain_id] = store_ids

                continue

            source_data[
                "chain_names"
            ][chain_id] = chain.get(
                "name_en_normalized",
                chain.get(
                    "Chain_name_store_file"
                ),
            )

        result[source] = source_data

    return result


def build_chains_extra(
    filename_chains: dict,
    chains: dict,
) -> dict:
    extras = {}

    for source, source_data in filename_chains.items():

        unknown_chain_ids = source_data[
            "unknown_chain_ids"
        ]

        if not unknown_chain_ids:
            continue

        known_chain_ids = [
            chain_id
            for chain_id in source_data["chain_ids"]
            if chain_id not in PLACEHOLDER_CHAIN_IDS
            and chain_id in chains
        ]

        if len(known_chain_ids) != 1:
            logger.error(
                "Cannot create chains_extra for source '%s': "
                "expected exactly one known chain, found %d: %s",
                source,
                len(known_chain_ids),
                ", ".join(known_chain_ids),
            )
            continue

        known_chain_id = known_chain_ids[0]
        known_chain = chains[known_chain_id]

        for unknown_chain_id in unknown_chain_ids:
            extra_chain = dict(known_chain)

            extras[unknown_chain_id] = extra_chain

            logger.warning(
                "Adding extra chain: "
                "source='%s', chain_id='%s', "
                "copied from chain_id='%s'",
                source,
                unknown_chain_id,
                known_chain_id,
            )

    extras["0000000000000"] = dict(
        PLACEHOLDER_CHAIN
    )

    return extras


def validate_filename_chains(
    filename_chains: dict,
    chains: dict,
) -> None:
    for source, data in filename_chains.items():

        chain_ids = data["chain_ids"]

        if len(chain_ids) > 1:
            logger.warning(
                "Source '%s' publishes %d chain IDs: %s",
                source,
                len(chain_ids),
                ", ".join(chain_ids),
            )

        for chain_id in data[
            "placeholder_chain_ids"
        ]:
            logger.warning(
                "Placeholder chain ID: "
                "source='%s', chain_id='%s'",
                source,
                chain_id,
            )

        for chain_id in data[
            "unknown_chain_ids"
        ]:
            logger.error(
                "UNKNOWN CHAIN: "
                "source='%s', chain_id='%s' "
                "is not present in chains.json",
                source,
                chain_id,
            )

            store_ids = data[
                "unknown_store_ids"
            ].get(chain_id, [])

            if store_ids:
                logger.error(
                    "UNKNOWN CHAIN STORES: "
                    "source='%s', chain_id='%s', "
                    "store_ids=%s",
                    source,
                    chain_id,
                    ", ".join(store_ids),
                )

        for chain_id in chain_ids:
            if chain_id in PLACEHOLDER_CHAIN_IDS:
                continue

            chain = chains.get(chain_id)

            if chain is None:
                continue

            expected_source = chain.get(
                "name_en_normalized"
            )

            if (
                expected_source
                and source != expected_source
            ):
                logger.warning(
                    "SOURCE/CHAIN MISMATCH: "
                    "source='%s', chain_id='%s', "
                    "chains.json name='%s'",
                    source,
                    chain_id,
                    expected_source,
                )


def log_filename_chains_changes(
    previous: dict,
    current: dict,
) -> None:
    if not previous:
        logger.info(
            "No previous filename_chains.json found"
        )
        return

    if previous == current:
        logger.info(
            "No changes detected in filename_chains.json"
        )
        return

    previous_sources = set(previous)
    current_sources = set(current)

    for source in sorted(
        current_sources - previous_sources
    ):
        logger.info(
            "NEW SOURCE discovered: '%s'",
            source,
        )

    for source in sorted(
        previous_sources - current_sources
    ):
        logger.info(
            "SOURCE REMOVED: '%s'",
            source,
        )

    for source in sorted(
        previous_sources & current_sources
    ):
        old_ids = set(
            previous[source]["chain_ids"]
        )
        new_ids = set(
            current[source]["chain_ids"]
        )

        for chain_id in sorted(
            new_ids - old_ids
        ):
            logger.info(
                "NEW CHAIN ID discovered: "
                "source='%s', chain_id='%s'",
                source,
                chain_id,
            )

        for chain_id in sorted(
            old_ids - new_ids
        ):
            logger.info(
                "CHAIN ID REMOVED: "
                "source='%s', chain_id='%s'",
                source,
                chain_id,
            )


def write_json(
    path: Path,
    data: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4,
        )

        file.write("\n")


def write_filename_chains(
    filename_chains: dict,
) -> None:
    write_json(
        OUTPUT_FILE,
        filename_chains,
    )

    logger.info(
        "Filename chains written to %s",
        OUTPUT_FILE,
    )


def write_chains_extra(
    chains_extra: dict,
) -> None:
    write_json(
        CHAINS_EXTRA_FILE,
        chains_extra,
    )

    logger.info(
        "Extra chains written to %s",
        CHAINS_EXTRA_FILE,
    )


def main() -> None:
    chains = load_chains()
    records = load_file_tracking()

    previous_filename_chains = (
        load_previous_filename_chains()
    )

    filename_chains = build_filename_chains(
        records,
        chains,
    )

    log_filename_chains_changes(
        previous_filename_chains,
        filename_chains,
    )

    validate_filename_chains(
        filename_chains,
        chains,
    )

    chains_extra = build_chains_extra(
        filename_chains,
        chains,
    )

    write_filename_chains(
        filename_chains,
    )

    write_chains_extra(
        chains_extra,
    )


if __name__ == "__main__":
    main()