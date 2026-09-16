import gzip
import json
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET


BASE_DIR = Path(__file__).resolve().parents[2]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
REFERENCE_DIR = BASE_DIR / "data" / "reference"

CHAINS_FILE = REFERENCE_DIR / "chains.json"
EXTRA_CHAINS_FILE = REFERENCE_DIR / "extra_chains.json"

REPORT_DIR = BASE_DIR / "inspection" / "reports"

REPORT_FILE = REPORT_DIR / "invalid_itemcodes_report.txt"
JSON_FILE = REPORT_DIR / "invalid_itemcodes.json"

FILE_WORKERS = 12

# Progress is printed every N completed files.
PROGRESS_EVERY = 25


# ----------------------------------------------------------------------
# Chain metadata
# ----------------------------------------------------------------------

def load_chain_names():
    """
    Returns:

        {
            chain_id: normalized English name
        }

    chains.json and extra_chains.json are merged.
    extra_chains.json takes precedence.
    """
    chains = {}

    for path in (CHAINS_FILE, EXTRA_CHAINS_FILE):
        if not path.exists():
            continue

        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        for chain_id, metadata in data.items():
            if not isinstance(metadata, dict):
                continue

            name = metadata.get("name_en_normalized")

            if name:
                chains[str(chain_id)] = name

    return chains


# ----------------------------------------------------------------------
# Latest PriceFull files
# ----------------------------------------------------------------------

def get_latest_pricefull_files():
    """
    Walk:

        data/feeds/{chain_id}/{store_id}/pricesfull/

    and return the newest physical file for every store.
    """
    latest_files = []

    if not FEEDS_DIR.exists():
        return latest_files

    for chain_dir in FEEDS_DIR.iterdir():
        if not chain_dir.is_dir():
            continue

        chain_id = chain_dir.name

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            store_id = store_dir.name
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

            latest = max(
                files,
                key=lambda path: path.stat().st_mtime,
            )

            latest_files.append(
                (
                    chain_id,
                    store_id,
                    latest,
                )
            )

    return latest_files


# ----------------------------------------------------------------------
# XML reading
# ----------------------------------------------------------------------

def iter_xml_from_path(path):
    """
    Yield XML events from:

        .xml
        .gz
        .xml.gz
        .zip
        extensionless / unknown files

    Filename extensions are treated as hints.
    """

    suffixes = [suffix.lower() for suffix in path.suffixes]

    def iter_zip():
        with zipfile.ZipFile(path) as zf:
            members = [
                name
                for name in zf.namelist()
                if not name.endswith("/")
                and (
                    name.lower().endswith(".xml")
                    or name.lower().endswith(".xml.gz")
                )
            ]

            if not members:
                raise ValueError(
                    "ZIP contains no XML files"
                )

            for member in members:
                with zf.open(member) as raw:
                    if member.lower().endswith(".gz"):
                        with gzip.GzipFile(
                            fileobj=raw
                        ) as xml_file:
                            yield from ET.iterparse(
                                xml_file,
                                events=("end",),
                            )
                    else:
                        yield from ET.iterparse(
                            raw,
                            events=("end",),
                        )

    # ZIP
    if ".zip" in suffixes:
        yield from iter_zip()
        return

    # GZIP
    if ".gz" in suffixes:
        try:
            with gzip.open(path, "rb") as f:
                yield from ET.iterparse(
                    f,
                    events=("end",),
                )

            return

        except (
            gzip.BadGzipFile,
            OSError,
            EOFError,
            ET.ParseError,
        ):
            yield from iter_zip()
            return

    # XML
    if ".xml" in suffixes:
        with path.open("rb") as f:
            yield from ET.iterparse(
                f,
                events=("end",),
            )

        return

    # Unknown / extensionless
    try:
        with gzip.open(path, "rb") as f:
            yield from ET.iterparse(
                f,
                events=("end",),
            )

        return

    except (
        gzip.BadGzipFile,
        OSError,
        EOFError,
        ET.ParseError,
    ):
        pass

    try:
        yield from iter_zip()
        return

    except zipfile.BadZipFile:
        pass

    with path.open("rb") as f:
        yield from ET.iterparse(
            f,
            events=("end",),
        )


def local_name(tag):
    """
    Handles XML namespaces:

        {namespace}ItemCode -> itemcode
    """
    if not isinstance(tag, str):
        return ""

    return tag.rsplit("}", 1)[-1].lower()


# ----------------------------------------------------------------------
# GTIN
# ----------------------------------------------------------------------

GTIN_LENGTHS = {8, 12, 13, 14}


def gtin_checksum_valid(code):
    if not code.isdigit():
        return False

    if len(code) not in GTIN_LENGTHS:
        return False

    digits = [int(x) for x in code]

    check_digit = digits[-1]
    body = digits[:-1]

    total = 0
    weight = 3

    for digit in reversed(body):
        total += digit * weight
        weight = 1 if weight == 3 else 3

    calculated = (10 - (total % 10)) % 10

    return calculated == check_digit


def expected_check_digit(body):
    if not body.isdigit():
        return None

    total = 0
    weight = 3

    for digit in reversed(body):
        total += int(digit) * weight
        weight = 1 if weight == 3 else 3

    return str(
        (10 - (total % 10)) % 10
    )


def corrected_gtin(code):
    if not code.isdigit():
        return None

    if len(code) not in GTIN_LENGTHS:
        return None

    body = code[:-1]

    return body + expected_check_digit(body)


# ----------------------------------------------------------------------
# Code patterns
# ----------------------------------------------------------------------

def detect_patterns(code):
    patterns = []

    if not code.isdigit():
        patterns.append("non_numeric")
        return patterns

    if len(set(code)) == 1:
        patterns.append("all_same_digit")

    if len(code) >= 4 and code == code[::-1]:
        patterns.append("palindrome")

    if len(code) >= 6:
        if code.startswith("0"):
            patterns.append("leading_zero")

        if code.endswith("0"):
            patterns.append("trailing_zero")

    if len(code) >= 6:
        if len(set(code)) <= 3:
            patterns.append("low_digit_diversity")

    for block_size in range(
        1,
        len(code) // 2 + 1,
    ):
        if len(code) % block_size != 0:
            continue

        block = code[:block_size]

        if block * (len(code) // block_size) == code:
            if len(block) < len(code):
                patterns.append("repeated_block")
                break

    if len(code) >= 4:
        ascending = all(
            int(code[i + 1]) == int(code[i]) + 1
            for i in range(len(code) - 1)
        )

        descending = all(
            int(code[i + 1]) == int(code[i]) - 1
            for i in range(len(code) - 1)
        )

        if ascending:
            patterns.append("sequential_ascending")

        if descending:
            patterns.append("sequential_descending")

    return patterns


def code_prefixes(code):
    if not code.isdigit():
        return {}

    prefixes = {}

    for length in (2, 3, 4, 5):
        if len(code) >= length:
            prefixes[str(length)] = code[:length]

    return prefixes


# ----------------------------------------------------------------------
# One-pass file worker
# ----------------------------------------------------------------------

def inspect_pricefull_file(
    chain_id,
    store_id,
    path,
):
    """
    Read ONE PriceFull exactly ONCE.

    During that read we collect BOTH:

      1. invalid GTIN-shaped codes
      2. valid GTIN codes

    This eliminates the expensive second XML parsing pass.
    """

    invalid_counter = Counter()
    valid_counter = Counter()

    try:
        for _, element in iter_xml_from_path(path):
            if local_name(element.tag) != "itemcode":
                element.clear()
                continue

            if element.text:
                code = element.text.strip()

                if code:
                    if (
                        code.isdigit()
                        and len(code) in GTIN_LENGTHS
                    ):
                        if gtin_checksum_valid(code):
                            valid_counter[code] += 1
                        else:
                            invalid_counter[code] += 1

            element.clear()

    except Exception as exc:
        return {
            "chain_id": chain_id,
            "store_id": store_id,
            "path": path,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
            "invalid_counter": None,
            "valid_counter": None,
        }

    return {
        "chain_id": chain_id,
        "store_id": store_id,
        "path": path,
        "error": None,
        "invalid_counter": invalid_counter,
        "valid_counter": valid_counter,
    }


# ----------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------

def relative_path(path):
    try:
        return str(
            path.relative_to(BASE_DIR)
        )
    except ValueError:
        return str(path)


def format_percentage(value):
    return f"{value:.2f}%"


def sorted_counter_dict(counter):
    return dict(
        sorted(
            counter.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    )


def safe_timestamp(path):
    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime
        ).isoformat(
            timespec="seconds"
        )
    except OSError:
        return None


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    chain_names = load_chain_names()
    latest_files = get_latest_pricefull_files()

    total_files = len(latest_files)

    print(
        f"Latest PriceFull files found: "
        f"{total_files:,}",
        flush=True,
    )

    # ------------------------------------------------------------
    # Global evidence structures
    # ------------------------------------------------------------

    # INVALID
    code_occurrences = Counter()
    code_chains = defaultdict(set)
    code_stores = defaultdict(set)
    code_files = defaultdict(set)

    code_chain_occurrences = defaultdict(Counter)
    code_chain_stores = defaultdict(
        lambda: defaultdict(set)
    )
    code_chain_files = defaultdict(
        lambda: defaultdict(set)
    )

    code_file_observations = defaultdict(list)

    body_codes = defaultdict(set)
    body_chains = defaultdict(set)
    body_stores = defaultdict(set)

    prefix_counts = defaultdict(Counter)

    # VALID
    valid_code_occurrences = Counter()
    valid_code_chains = defaultdict(set)
    valid_code_stores = defaultdict(set)
    valid_code_files = defaultdict(set)

    unreadable_files = []

    chain_files = Counter()
    chain_failed_files = Counter()

    # ------------------------------------------------------------
    # One pass over every file
    # ------------------------------------------------------------

    print(
        f"Inspecting {total_files:,} PriceFull files "
        f"with {FILE_WORKERS} workers...",
        flush=True,
    )

    completed = 0

    with ThreadPoolExecutor(
        max_workers=FILE_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                inspect_pricefull_file,
                chain_id,
                store_id,
                path,
            ): (
                chain_id,
                store_id,
                path,
            )
            for chain_id, store_id, path
            in latest_files
        }

        for future in as_completed(futures):

            completed += 1

            chain_id, store_id, path = (
                futures[future]
            )

            result = future.result()

            # ----------------------------------------------------
            # Progress
            # ----------------------------------------------------

            if (
                completed % PROGRESS_EVERY == 0
                or completed == total_files
            ):
                percent = (
                    completed / total_files * 100
                    if total_files
                    else 100
                )

                print(
                    f"  [{completed:,}/{total_files:,}] "
                    f"{percent:6.2f}% | "
                    f"invalid codes: "
                    f"{len(code_occurrences):,} | "
                    f"valid GTINs seen: "
                    f"{len(valid_code_occurrences):,}",
                    flush=True,
                )

            # ----------------------------------------------------
            # Failed file
            # ----------------------------------------------------

            if result["error"]:

                chain_failed_files[
                    chain_id
                ] += 1

                unreadable_files.append(
                    {
                        "chain": chain_id,
                        "store": store_id,
                        "file": relative_path(path),
                        "error": result["error"],
                    }
                )

                continue

            chain_files[chain_id] += 1

            invalid_counter = result[
                "invalid_counter"
            ]

            valid_counter = result[
                "valid_counter"
            ]

            # ----------------------------------------------------
            # VALID GTINs
            # ----------------------------------------------------

            for code, occurrences in (
                valid_counter.items()
            ):

                valid_code_occurrences[
                    code
                ] += occurrences

                valid_code_chains[
                    code
                ].add(chain_id)

                valid_code_stores[
                    code
                ].add(
                    (chain_id, store_id)
                )

                valid_code_files[
                    code
                ].add(
                    (
                        chain_id,
                        store_id,
                        relative_path(path),
                    )
                )

            # ----------------------------------------------------
            # INVALID GTIN-shaped codes
            # ----------------------------------------------------

            for code, occurrences in (
                invalid_counter.items()
            ):

                code_occurrences[
                    code
                ] += occurrences

                code_chains[
                    code
                ].add(chain_id)

                code_stores[
                    code
                ].add(
                    (chain_id, store_id)
                )

                code_files[
                    code
                ].add(
                    (
                        chain_id,
                        store_id,
                        relative_path(path),
                    )
                )

                code_chain_occurrences[
                    code
                ][chain_id] += occurrences

                code_chain_stores[
                    code
                ][chain_id].add(store_id)

                code_chain_files[
                    code
                ][chain_id].add(
                    relative_path(path)
                )

                code_file_observations[
                    code
                ].append(
                    {
                        "chain": chain_id,
                        "store": store_id,
                        "file": relative_path(path),
                        "occurrences": occurrences,
                        "modified_at": safe_timestamp(path),
                    }
                )

                body = code[:-1]

                body_codes[body].add(code)
                body_chains[body].add(chain_id)

                body_stores[body].add(
                    (chain_id, store_id)
                )

                for (
                    prefix_length,
                    prefix,
                ) in code_prefixes(code).items():

                    prefix_counts[
                        prefix_length
                    ][prefix] += 1

    # ------------------------------------------------------------
    # Build detailed records
    # ------------------------------------------------------------

    print(
        f"Finished file inspection. "
        f"Building {len(code_occurrences):,} invalid-code records...",
        flush=True,
    )

    records = []

    # Precompute number of latest files per chain.
    # This avoids scanning latest_files for EVERY invalid code.
    chain_total_stores = Counter()

    for chain_id, store_id, path in latest_files:
        chain_total_stores[chain_id] += 1

    for code, occurrences in code_occurrences.items():

        length = len(code)

        observed_check_digit = code[-1]
        body = code[:-1]

        expected = expected_check_digit(body)
        corrected = corrected_gtin(code)

        chains = sorted(
            code_chains[code]
        )

        stores = sorted(
            (
                {
                    "chain": chain_id,
                    "chain_name": chain_names.get(
                        chain_id,
                        "UNKNOWN",
                    ),
                    "store": store_id,
                }
                for chain_id, store_id
                in code_stores[code]
            ),
            key=lambda item: (
                item["chain_name"].lower(),
                item["chain"],
                item["store"],
            ),
        )

        chain_distribution = []

        for (
            chain_id,
            chain_occurrences,
        ) in sorted(
            code_chain_occurrences[code].items(),
            key=lambda item: (
                -item[1],
                chain_names.get(
                    item[0],
                    "",
                ).lower(),
                item[0],
            ),
        ):

            chain_store_count = len(
                code_chain_stores[
                    code
                ][chain_id]
            )

            total_chain_stores = (
                chain_total_stores[chain_id]
            )

            coverage = (
                chain_store_count
                / total_chain_stores
                * 100
                if total_chain_stores
                else 0
            )

            chain_distribution.append(
                {
                    "chain": chain_id,
                    "chain_name": chain_names.get(
                        chain_id,
                        "UNKNOWN",
                    ),
                    "occurrences": chain_occurrences,
                    "stores": chain_store_count,
                    "store_coverage_percent": round(
                        coverage,
                        2,
                    ),
                    "files": len(
                        code_chain_files[
                            code
                        ][chain_id]
                    ),
                }
            )

        same_body_codes = sorted(
            body_codes[body]
        )

        other_body_codes = [
            value
            for value in same_body_codes
            if value != code
        ]

        corrected_found_among_invalid = (
            corrected in body_codes[body]
            and corrected != code
        )

        record = {
            "code": code,
            "length": length,
            "occurrences": occurrences,
            "files": len(
                code_files[code]
            ),
            "stores": len(
                code_stores[code]
            ),
            "chains": len(
                code_chains[code]
            ),
            "chain_ids": chains,
            "chain_names": [
                chain_names.get(
                    chain_id,
                    "UNKNOWN",
                )
                for chain_id in chains
            ],
            "observed_check_digit": (
                observed_check_digit
            ),
            "expected_check_digit": expected,
            "corrected_gtin_candidate": corrected,
            "body_without_check_digit": body,
            "same_body_codes": same_body_codes,
            "other_same_body_codes": other_body_codes,
            "corrected_candidate_found_among_invalid": (
                corrected_found_among_invalid
            ),
            "patterns": detect_patterns(code),
            "prefixes": code_prefixes(code),
            "chain_distribution": chain_distribution,
            "stores_detail": stores,
            "file_observations": sorted(
                code_file_observations[code],
                key=lambda item: (
                    item["chain"],
                    item["store"],
                    item["file"],
                ),
            ),
        }

        records.append(record)

    # ------------------------------------------------------------
    # Corrected GTIN evidence
    #
    # NO SECOND XML PASS.
    #
    # All valid GTINs were collected during the first pass.
    # ------------------------------------------------------------

    print(
        f"Checking corrected GTIN relationships "
        f"for {len(records):,} invalid codes...",
        flush=True,
    )

    corrected_relationships_found = 0

    for index, record in enumerate(records, start=1):

        candidate = record[
            "corrected_gtin_candidate"
        ]

        if not candidate:
            continue

        valid_stores = valid_code_stores.get(
            candidate,
            set(),
        )

        valid_exists = (
            candidate
            in valid_code_occurrences
        )

        if valid_exists:
            corrected_relationships_found += 1

        invalid_stores = code_stores[
            record["code"]
        ]

        same_store_pairs = sorted(
            invalid_stores & valid_stores
        )

        record[
            "corrected_candidate"
        ] = {
            "code": candidate,
            "exists_as_valid_gtin": valid_exists,
            "occurrences": valid_code_occurrences.get(
                candidate,
                0,
            ),
            "chains": len(
                valid_code_chains.get(
                    candidate,
                    set(),
                )
            ),
            "stores": len(valid_stores),
            "chain_ids": sorted(
                valid_code_chains.get(
                    candidate,
                    set(),
                )
            ),
            "stores_detail": sorted(
                (
                    {
                        "chain": chain_id,
                        "chain_name": chain_names.get(
                            chain_id,
                            "UNKNOWN",
                        ),
                        "store": store_id,
                    }
                    for chain_id, store_id
                    in valid_stores
                ),
                key=lambda item: (
                    item["chain_name"].lower(),
                    item["chain"],
                    item["store"],
                ),
            ),
            "same_store_pairs": [
                {
                    "chain": chain_id,
                    "chain_name": chain_names.get(
                        chain_id,
                        "UNKNOWN",
                    ),
                    "store": store_id,
                }
                for chain_id, store_id
                in same_store_pairs
            ],
            "same_store_pair_count": len(
                same_store_pairs
            ),
        }

        if (
            index % 10000 == 0
            or index == len(records)
        ):
            print(
                f"  Corrected candidates checked: "
                f"{index:,}/{len(records):,}",
                flush=True,
            )

    print(
        f"Corrected GTINs found as valid: "
        f"{corrected_relationships_found:,}",
        flush=True,
    )

    # ------------------------------------------------------------
    # Investigation flags + score
    # ------------------------------------------------------------

    for record in records:

        score = 0
        flags = []

        if record["stores"] >= 2:
            score += 3
            flags.append("multi_store")

        if record["stores"] >= 10:
            score += 3
            flags.append("high_store_repetition")

        if record["chains"] == 1:
            score += 3
            flags.append("chain_specific")

        if record["chains"] >= 2:
            score += 6
            flags.append("cross_chain_collision")

        if record["occurrences"] >= 100:
            score += 2
            flags.append("high_occurrence")

        if record["occurrences"] >= 1000:
            score += 3
            flags.append("very_high_occurrence")

        candidate = record.get(
            "corrected_candidate"
        )

        if candidate:

            if candidate[
                "exists_as_valid_gtin"
            ]:
                score += 8
                flags.append(
                    "corrected_gtin_exists"
                )

            if candidate[
                "same_store_pair_count"
            ]:
                score += 12
                flags.append(
                    "invalid_and_valid_same_store"
                )

        if len(
            record["same_body_codes"]
        ) > 1:
            score += 5
            flags.append(
                "same_body_multiple_checksums"
            )

        patterns = set(
            record["patterns"]
        )

        if "leading_zero" in patterns:
            score += 1
            flags.append("leading_zero")

        if (
            "all_same_digit" in patterns
            or "repeated_block" in patterns
            or "sequential_ascending" in patterns
            or "sequential_descending" in patterns
        ):
            score += 4
            flags.append(
                "suspicious_numeric_pattern"
            )

        max_coverage = max(
            (
                item[
                    "store_coverage_percent"
                ]
                for item in record[
                    "chain_distribution"
                ]
            ),
            default=0,
        )

        if max_coverage >= 50:
            score += 5
            flags.append(
                "high_chain_store_coverage"
            )

        if max_coverage >= 90:
            score += 5
            flags.append(
                "very_high_chain_store_coverage"
            )

        if (
            record["stores"] == 1
            and record["occurrences"] == 1
        ):
            flags.append("singleton")

        if score >= 20:
            interest = "HIGH"
        elif score >= 10:
            interest = "MEDIUM"
        else:
            interest = "LOW"

        record[
            "investigation_score"
        ] = score

        record["interest"] = interest

        record[
            "evidence_flags"
        ] = sorted(set(flags))

    # ------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------

    records.sort(
        key=lambda record: (
            -record["investigation_score"],
            -record["stores"],
            -record["chains"],
            -record["occurrences"],
            record["code"],
        )
    )

    # ------------------------------------------------------------
    # Global summary
    # ------------------------------------------------------------

    total_invalid_codes = len(records)

    invalid_occurrences = sum(
        record["occurrences"]
        for record in records
    )

    invalid_store_pairs = set()

    for record in records:
        invalid_store_pairs.update(
            code_stores[
                record["code"]
            ]
        )

    invalid_chains = set()

    for record in records:
        invalid_chains.update(
            code_chains[
                record["code"]
            ]
        )

    interest_counts = Counter(
        record["interest"]
        for record in records
    )

    flag_counts = Counter()

    for record in records:
        flag_counts.update(
            record["evidence_flags"]
        )

    length_counts = Counter(
        record["length"]
        for record in records
    )

    cross_chain_codes = [
        record
        for record in records
        if record["chains"] >= 2
    ]

    multi_store_codes = [
        record
        for record in records
        if record["stores"] >= 2
    ]

    corrected_found_codes = [
        record
        for record in records
        if record.get(
            "corrected_candidate",
            {},
        ).get(
            "exists_as_valid_gtin",
            False,
        )
    ]

    same_store_pair_codes = [
        record
        for record in records
        if record.get(
            "corrected_candidate",
            {},
        ).get(
            "same_store_pair_count",
            0,
        ) > 0
    ]

    # ------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------

    print(
        "Writing JSON report...",
        flush=True,
    )

    json_data = {
        "report": {
            "generated_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "latest_pricefull_files": len(
                latest_files
            ),
            "chains_found": len(
                {
                    chain_id
                    for chain_id, _, _
                    in latest_files
                }
            ),
            "stores_found": len(
                latest_files
            ),
            "invalid_gtin_shaped_codes": (
                total_invalid_codes
            ),
            "invalid_occurrences": (
                invalid_occurrences
            ),
            "invalid_store_pairs": len(
                invalid_store_pairs
            ),
            "invalid_chains": len(
                invalid_chains
            ),
            "valid_gtins_seen": len(
                valid_code_occurrences
            ),
            "length_counts": dict(
                sorted(
                    length_counts.items()
                )
            ),
            "interest_counts": dict(
                interest_counts
            ),
            "evidence_flag_counts": (
                sorted_counter_dict(
                    flag_counts
                )
            ),
            "cross_chain_codes": len(
                cross_chain_codes
            ),
            "multi_store_codes": len(
                multi_store_codes
            ),
            "corrected_gtin_found": len(
                corrected_found_codes
            ),
            "invalid_and_valid_same_store": len(
                same_store_pair_codes
            ),
        },
        "codes": records,
        "unreadable_files": unreadable_files,
    }

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    JSON_FILE.write_text(
        json.dumps(
            json_data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ------------------------------------------------------------
    # Human-readable report
    # ------------------------------------------------------------

    print(
        "Building TXT report...",
        flush=True,
    )

    lines = []

    lines.append(
        "DISCARD 5 — INVALID GTIN ITEMCODE INVESTIGATION"
    )

    lines.append("=" * 70)
    lines.append("")

    lines.append(
        f"Latest PriceFull files inspected: "
        f"{len(latest_files):,}"
    )

    lines.append(
        f"Stores inspected: "
        f"{len(latest_files):,}"
    )

    lines.append(
        f"Chains found: "
        f"{len(set(chain_id for chain_id, _, _ in latest_files)):,}"
    )

    lines.append(
        f"Invalid GTIN-shaped unique codes: "
        f"{total_invalid_codes:,}"
    )

    lines.append(
        f"Invalid ItemCode occurrences: "
        f"{invalid_occurrences:,}"
    )

    lines.append("")

    lines.append("GENERAL SUMMARY")
    lines.append("-" * 70)

    lines.append("Invalid code lengths:")

    for length, count in sorted(
        length_counts.items()
    ):
        lines.append(
            f"  {length:>2} digits: "
            f"{count:>10,}"
        )

    lines.append("")

    lines.append(
        f"Codes appearing in multiple stores: "
        f"{len(multi_store_codes):,}"
    )

    lines.append(
        f"Codes appearing across multiple chains: "
        f"{len(cross_chain_codes):,}"
    )

    lines.append(
        f"Corrected GTIN candidate found as valid: "
        f"{len(corrected_found_codes):,}"
    )

    lines.append(
        f"Invalid + corrected GTIN in same store: "
        f"{len(same_store_pair_codes):,}"
    )

    lines.append("")

    lines.append("INVESTIGATION INTEREST")
    lines.append("-" * 70)

    for interest in (
        "HIGH",
        "MEDIUM",
        "LOW",
    ):
        lines.append(
            f"  {interest:<7}: "
            f"{interest_counts[interest]:,}"
        )

    lines.append("")

    lines.append("EVIDENCE FLAGS")
    lines.append("-" * 70)

    for flag, count in sorted(
        flag_counts.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):
        lines.append(
            f"  {flag:<38} "
            f"{count:>8,}"
        )

    # ------------------------------------------------------------
    # Top codes
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 70)
    lines.append("INVALID CODE INVESTIGATION")
    lines.append("=" * 70)

    MAX_DETAILED_CODES = 250

    for index, record in enumerate(
        records[:MAX_DETAILED_CODES],
        start=1,
    ):

        code = record["code"]

        lines.append("")
        lines.append(f"#{index}  {code}")
        lines.append("-" * 70)

        lines.append(
            f"Interest: "
            f"{record['interest']}"
        )

        lines.append(
            f"Investigation score: "
            f"{record['investigation_score']}"
        )

        lines.append(
            f"Length: "
            f"{record['length']}"
        )

        lines.append(
            f"Occurrences: "
            f"{record['occurrences']:,}"
        )

        lines.append(
            f"Files: "
            f"{record['files']:,}"
        )

        lines.append(
            f"Stores: "
            f"{record['stores']:,}"
        )

        lines.append(
            f"Chains: "
            f"{record['chains']:,}"
        )

        lines.append("")

        lines.append("Checksum:")

        lines.append(
            f"  Observed: "
            f"{record['observed_check_digit']}"
        )

        lines.append(
            f"  Expected: "
            f"{record['expected_check_digit']}"
        )

        lines.append(
            f"  Body: "
            f"{record['body_without_check_digit']}"
        )

        lines.append(
            f"  Corrected candidate: "
            f"{record['corrected_gtin_candidate']}"
        )

        candidate = record.get(
            "corrected_candidate"
        )

        if candidate:

            lines.append(
                f"  Corrected candidate exists as "
                f"valid GTIN: "
                f"{'YES' if candidate['exists_as_valid_gtin'] else 'NO'}"
            )

            if candidate[
                "exists_as_valid_gtin"
            ]:

                lines.append(
                    f"  Valid candidate occurrences: "
                    f"{candidate['occurrences']:,}"
                )

                lines.append(
                    f"  Valid candidate stores: "
                    f"{candidate['stores']:,}"
                )

                lines.append(
                    f"  Valid candidate chains: "
                    f"{candidate['chains']:,}"
                )

                lines.append(
                    f"  Same-store invalid/valid pairs: "
                    f"{candidate['same_store_pair_count']:,}"
                )

        lines.append("")
        lines.append("Same body codes:")

        for body_code in record[
            "same_body_codes"
        ]:

            marker = (
                " <-- THIS CODE"
                if body_code == code
                else ""
            )

            lines.append(
                f"  {body_code}{marker}"
            )

        lines.append("")
        lines.append("Evidence flags:")

        if record["evidence_flags"]:
            for flag in record[
                "evidence_flags"
            ]:
                lines.append(
                    f"  - {flag}"
                )
        else:
            lines.append("  - none")

        lines.append("")
        lines.append("Patterns:")

        if record["patterns"]:
            for pattern in record[
                "patterns"
            ]:
                lines.append(
                    f"  - {pattern}"
                )
        else:
            lines.append("  - none")

        lines.append("")
        lines.append("Chain distribution:")

        for chain in record[
            "chain_distribution"
        ]:

            lines.append(
                f"  {chain['chain_name']} "
                f"[{chain['chain']}]: "
                f"{chain['occurrences']:,} occurrences, "
                f"{chain['stores']:,} stores, "
                f"{chain['store_coverage_percent']:.2f}% "
                f"coverage"
            )

        lines.append("")

        if record["stores"] <= 50:

            lines.append("Stores:")

            for store in record[
                "stores_detail"
            ]:

                lines.append(
                    f"  {store['chain_name']} "
                    f"[{store['chain']}] "
                    f"store {store['store']}"
                )

        else:

            lines.append(
                f"Stores: "
                f"{record['stores']:,} "
                f"(full list in JSON)"
            )

    if len(records) > MAX_DETAILED_CODES:

        lines.append("")
        lines.append(
            f"... {len(records) - MAX_DETAILED_CODES:,} "
            f"additional codes omitted from the TXT report."
        )

        lines.append(
            "Full data is available in "
            "invalid_itemcodes.json."
        )

    # ------------------------------------------------------------
    # Cross-chain collisions
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 70)
    lines.append("CROSS-CHAIN COLLISIONS")
    lines.append("=" * 70)

    cross_chain_sorted = sorted(
        cross_chain_codes,
        key=lambda record: (
            -record["chains"],
            -record["stores"],
            -record["occurrences"],
            record["code"],
        ),
    )

    if cross_chain_sorted:

        for record in cross_chain_sorted[:100]:

            lines.append("")
            lines.append(
                f"{record['code']} — "
                f"{record['chains']} chains, "
                f"{record['stores']} stores, "
                f"{record['occurrences']:,} occurrences"
            )

            for chain in record[
                "chain_distribution"
            ]:

                lines.append(
                    f"  {chain['chain_name']} "
                    f"[{chain['chain']}]: "
                    f"{chain['stores']} stores"
                )

    else:

        lines.append(
            "No invalid codes were found across "
            "multiple chains."
        )

    # ------------------------------------------------------------
    # Same-store valid/invalid
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 70)
    lines.append(
        "INVALID + VALID CORRECTED GTIN IN SAME STORE"
    )
    lines.append("=" * 70)

    if same_store_pair_codes:

        for record in sorted(
            same_store_pair_codes,
            key=lambda item: (
                -item[
                    "corrected_candidate"
                ][
                    "same_store_pair_count"
                ],
                -item["occurrences"],
                item["code"],
            ),
        )[:100]:

            candidate = record[
                "corrected_candidate"
            ]

            lines.append("")
            lines.append(
                f"Invalid: "
                f"{record['code']}"
            )

            lines.append(
                f"Corrected: "
                f"{candidate['code']}"
            )

            lines.append(
                f"Same stores: "
                f"{candidate['same_store_pair_count']:,}"
            )

            for store in candidate[
                "same_store_pairs"
            ]:

                lines.append(
                    f"  {store['chain_name']} "
                    f"[{store['chain']}] "
                    f"store {store['store']}"
                )

    else:

        lines.append(
            "No invalid/corrected-valid same-store "
            "pairs found."
        )

    # ------------------------------------------------------------
    # Top chain-specific codes
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 70)
    lines.append(
        "HIGH STORE-COVERAGE CHAIN-SPECIFIC CODES"
    )
    lines.append("=" * 70)

    chain_specific = [
        record
        for record in records
        if record["chains"] == 1
    ]

    chain_specific.sort(
        key=lambda record: (
            -max(
                (
                    item[
                        "store_coverage_percent"
                    ]
                    for item in record[
                        "chain_distribution"
                    ]
                ),
                default=0,
            ),
            -record["stores"],
            -record["occurrences"],
            record["code"],
        )
    )

    for record in chain_specific[:100]:

        chain = record[
            "chain_distribution"
        ][0]

        lines.append(
            f"{record['code']} | "
            f"{chain['chain_name']} | "
            f"{chain['stores']} stores / "
            f"{chain['store_coverage_percent']:.2f}% | "
            f"{record['occurrences']:,} occurrences"
        )

    # ------------------------------------------------------------
    # Unreadable
    # ------------------------------------------------------------

    lines.append("")
    lines.append("=" * 70)
    lines.append("UNREADABLE FILES")
    lines.append("=" * 70)

    if unreadable_files:

        lines.append(
            f"Total unreadable files: "
            f"{len(unreadable_files):,}"
        )

        for entry in unreadable_files:

            lines.append("")
            lines.append(
                f"Chain: "
                f"{entry['chain']}"
            )

            lines.append(
                f"Store: "
                f"{entry['store']}"
            )

            lines.append(
                f"File:  "
                f"{entry['file']}"
            )

            lines.append(
                f"Error: "
                f"{entry['error']}"
            )

    else:

        lines.append("None.")

    # ------------------------------------------------------------
    # Write TXT
    # ------------------------------------------------------------

    print(
        "Writing TXT report...",
        flush=True,
    )

    REPORT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    # ------------------------------------------------------------
    # Final
    # ------------------------------------------------------------

    print("")
    print(
        f"Invalid codes found: "
        f"{total_invalid_codes:,}"
    )

    print(
        f"High-interest codes: "
        f"{interest_counts['HIGH']:,}"
    )

    print(
        f"Corrected GTIN candidates found: "
        f"{len(corrected_found_codes):,}"
    )

    print(
        f"Invalid + valid same-store pairs: "
        f"{len(same_store_pair_codes):,}"
    )

    print("")

    print(
        f"TXT report written to: "
        f"{REPORT_FILE}"
    )

    print(
        f"JSON report written to: "
        f"{JSON_FILE}"
    )


if __name__ == "__main__":
    main()