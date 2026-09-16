# inspection/token_vocabulary_report.py

import gzip
import json
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lxml import etree


BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
REFERENCE_DIR = BASE_DIR / "data" / "reference"

CHAINS_FILE = REFERENCE_DIR / "chains.json"
EXTRA_CHAINS_FILE = REFERENCE_DIR / "extra_chains.json"

VOCABULARY_FILE = REFERENCE_DIR / "product_name_vocabulary.json"

REPORT_FILE = (
    BASE_DIR
    / "inspection"
    / "reports"
    / "token_vocabulary_report.txt"
)

FILE_WORKERS = 12
TOP_TOKENS = 1000
MIN_ITEM_CODES = 20


def load_chain_names() -> dict:
    chains = {}

    for path in (CHAINS_FILE, EXTRA_CHAINS_FILE):
        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = data.values()

        for chain in data:
            chain_id = str(
                chain.get("chain_id", "")
            ).strip()

            if not chain_id:
                continue

            chains[chain_id] = chain.get(
                "name",
                chain.get("name_en", chain_id),
            )

    return chains


def get_latest_pricefull_files() -> list[tuple[str, str, Path]]:
    """
    Return the latest PriceFull file for every store.

    Local path intentionally ignores subchain:

        data/feeds/{chain_id}/{store_id}/pricesfull/

    Latest means newest filesystem modification time.
    """

    latest = []

    for chain_dir in FEEDS_DIR.iterdir():
        if not chain_dir.is_dir():
            continue

        chain_id = chain_dir.name

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            pricesfull_dir = store_dir / "pricesfull"

            if not pricesfull_dir.is_dir():
                continue

            files = [
                path
                for path in pricesfull_dir.iterdir()
                if path.is_file()
            ]

            if not files:
                continue

            latest_path = max(
                files,
                key=lambda path: path.stat().st_mtime,
            )

            latest.append(
                (
                    chain_id,
                    store_dir.name,
                    latest_path,
                )
            )

    return latest


def extract_items_from_file(file_obj):
    """
    Parse one PriceFull XML stream and yield:

        (ItemCode, ItemName)

    Uses the same structure as StoreXmlParser:

        ./Items/Item
    """

    root = etree.parse(file_obj).getroot()

    for item in root.findall("./Items/Item"):
        item_code = item.findtext("ItemCode")
        item_name = item.findtext("ItemName")

        if item_code and item_name:
            yield item_code, item_name


def extract_from_zip(path: Path):
    """
    Open a ZIP file and extract all ItemCode/ItemName pairs.

    The first non-directory member is treated as the feed.
    """

    with zipfile.ZipFile(path) as archive:
        members = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
        ]

        if not members:
            raise ValueError(
                f"ZIP contains no files: {path}"
            )

        with archive.open(members[0]) as f:
            yield from extract_items_from_file(f)


def extract_items(path: Path):
    """
    Parse one PriceFull and return all ItemCode/ItemName pairs.

    Filename extensions are treated as hints, not guaranteed truth.

    Supported formats:

        .zip  -> ZIP
        .gz   -> GZIP, then ZIP fallback
        .xml  -> XML
        no extension / unknown -> GZIP, ZIP, then XML

    This handles cases where:
        - a gzip file has no .gz extension
        - a ZIP file is incorrectly named .gz
        - an extensionless file is plain XML
    """

    suffixes = [
        suffix.lower()
        for suffix in path.suffixes
    ]

    # ---------------------------------------------------------
    # ZIP
    # ---------------------------------------------------------

    if ".zip" in suffixes:
        yield from extract_from_zip(path)
        return

    # ---------------------------------------------------------
    # GZIP
    # ---------------------------------------------------------

    if ".gz" in suffixes:
        try:
            with gzip.open(path, "rb") as f:
                yield from extract_items_from_file(f)
                return

        except (
            gzip.BadGzipFile,
            OSError,
            EOFError,
        ):
            # Some files are incorrectly named .gz but are
            # actually ZIP archives.
            try:
                yield from extract_from_zip(path)
                return

            except zipfile.BadZipFile:
                raise

    # ---------------------------------------------------------
    # XML
    # ---------------------------------------------------------

    if ".xml" in suffixes:
        with path.open("rb") as f:
            yield from extract_items_from_file(f)

        return

    # ---------------------------------------------------------
    # Unknown / extensionless
    # ---------------------------------------------------------

    # First try GZIP.
    try:
        with gzip.open(path, "rb") as f:
            yield from extract_items_from_file(f)
            return

    except (
        gzip.BadGzipFile,
        OSError,
        EOFError,
    ):
        pass

    # Then try ZIP.
    try:
        yield from extract_from_zip(path)
        return

    except zipfile.BadZipFile:
        pass

    # Finally assume plain XML.
    with path.open("rb") as f:
        yield from extract_items_from_file(f)


def normalize_token(token: str) -> str:
    token = token.strip()

    if not token:
        return ""

    token = token.strip(
        ".,;:!?()[]{}<>\"'“”‘’/\\|+-_=*#"
    )

    return token.lower()


def tokenize(name: str) -> list[str]:
    if not name:
        return []

    tokens = []

    for raw_token in name.split():
        token = normalize_token(raw_token)

        if token:
            tokens.append(token)

    return tokens


def process_file(job):
    """
    Process one PriceFull file independently.

    Returns compact per-file aggregates so worker threads
    do not mutate global state.
    """

    chain_id, store_id, path = job

    token_item_codes = defaultdict(set)
    token_occurrences = defaultdict(int)
    token_examples = defaultdict(set)

    try:
        for item_code, item_name in extract_items(path):
            tokens = tokenize(item_name)

            if not tokens:
                continue

            for token in tokens:
                token_item_codes[token].add(
                    item_code
                )

                token_occurrences[token] += 1

                if len(token_examples[token]) < 5:
                    token_examples[token].add(
                        item_name
                    )

        return (
            chain_id,
            store_id,
            path,
            token_item_codes,
            token_occurrences,
            token_examples,
            None,
        )

    except Exception as exc:
        return (
            chain_id,
            store_id,
            path,
            None,
            None,
            None,
            repr(exc),
        )


def write_report(
    token_item_codes,
    token_chains,
    token_occurrences,
    token_examples,
    errors,
):
    rows = []

    for token, item_codes in token_item_codes.items():
        item_code_count = len(item_codes)

        if item_code_count < MIN_ITEM_CODES:
            continue

        rows.append(
            (
                token,
                item_code_count,
                len(token_chains[token]),
                token_occurrences[token],
                sorted(token_examples[token])[:5],
            )
        )

    rows.sort(
        key=lambda row: (row[1], row[2], row[3]),
        reverse=True,
    )

    rows = rows[:TOP_TOKENS]

    # JSON vocabulary reference
    VOCABULARY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with VOCABULARY_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            {"words": [row[0] for row in rows]},
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Human-readable investigation report
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with REPORT_FILE.open("w", encoding="utf-8") as f:
        f.write("TOKEN VOCABULARY REPORT\n")
        f.write("=======================\n\n")
        f.write(f"Tokens shown: {len(rows)}\n")
        f.write(f"Minimum ItemCodes: {MIN_ITEM_CODES}\n")
        f.write(f"Files with errors: {len(errors)}\n\n")

        for index, (
            token,
            item_code_count,
            chain_count,
            occurrence_count,
            examples,
        ) in enumerate(rows, 1):
            f.write(f"{index}. {token}\n")
            f.write(f"   ItemCodes: {item_code_count}\n")
            f.write(f"   Chains: {chain_count}\n")
            f.write(f"   Occurrences: {occurrence_count}\n")
            f.write("   Examples:\n")

            for example in examples:
                f.write(f"      - {example}\n")

            f.write("\n")

        if errors:
            f.write("\nFILES WITH ERRORS\n")
            f.write("=================\n\n")

            for chain_id, store_id, path, error in errors:
                f.write(f"{chain_id}/{store_id}: {path}\n")
                f.write(f"   {error}\n\n")



def main():
    chain_names = load_chain_names()

    jobs = get_latest_pricefull_files()

    print(
        f"Found {len(jobs):,} latest PriceFull files."
    )

    token_item_codes = defaultdict(set)
    token_chains = defaultdict(set)
    token_occurrences = defaultdict(int)
    token_examples = defaultdict(set)

    errors = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=FILE_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                process_file,
                job,
            )
            for job in jobs
        ]

        for future in as_completed(futures):
            (
                chain_id,
                store_id,
                path,
                local_item_codes,
                local_occurrences,
                local_examples,
                error,
            ) = future.result()

            completed += 1

            if completed % 100 == 0:
                print(
                    f"Processed "
                    f"{completed:,}/{len(jobs):,} files..."
                )

            if error:
                errors.append(
                    (
                        chain_id,
                        store_id,
                        path,
                        error,
                    )
                )
                continue

            for token, item_codes in local_item_codes.items():
                token_item_codes[token].update(
                    item_codes
                )

                token_chains[token].add(
                    chain_id
                )

            for token, count in local_occurrences.items():
                token_occurrences[token] += count

            for token, examples in local_examples.items():
                remaining = (
                    5
                    - len(token_examples[token])
                )

                if remaining > 0:
                    token_examples[token].update(
                        list(examples)[:remaining]
                    )

    write_report(
        token_item_codes=token_item_codes,
        token_chains=token_chains,
        token_occurrences=token_occurrences,
        token_examples=token_examples,
        errors=errors,
    )

    print()
    print(
        f"Report written to: {REPORT_FILE}"
    )

    if errors:
        print(
            f"Files with errors: {len(errors):,}"
        )

    print(
        f"Chains known: {len(chain_names):,}"
    )


if __name__ == "__main__":
    main()