import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path


"""
Dedicated inspection for Full vs normal feed sizes.

Checks today's:

    pricesfull vs prices
    promosfull vs promos

A normal file whose size is >= 80% of the corresponding Full file
is considered suspicious.

This script does NOT open or parse the feed contents.
It only checks today's filenames, paths, and file sizes.

Reports:

    monitoring/data/prices_vs_pricesfull_report.json
    monitoring/data/promos_vs_promofull_report.json
"""


# ============================================================
# Paths / configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

FEEDS_DIR = BASE_DIR / "data" / "feeds"
REPORTS_DIR = BASE_DIR / "monitoring" / "data"

PRICES_REPORT = (
    REPORTS_DIR / "prices_vs_pricesfull_report.json"
)

PROMOS_REPORT = (
    REPORTS_DIR / "promos_vs_promofull_report.json"
)

SIZE_THRESHOLD = 0.80


# ============================================================
# Filename date
# ============================================================

def extract_date_from_filename(filename):
    """
    Find YYYYMMDD anywhere in the filename.
    """
    matches = re.findall(r"(20\d{6})", filename)

    for value in matches:
        try:
            return date(
                int(value[:4]),
                int(value[4:6]),
                int(value[6:8]),
            )

        except ValueError:
            continue

    return None


# ============================================================
# Store folders
# ============================================================

def discover_store_folders():
    """
    Count stores from the actual filesystem structure.

    Expected:

        data/feeds/{chain}/{store}/...

    The store directory name is treated as the store ID.
    """
    stores_by_chain = defaultdict(set)

    if not FEEDS_DIR.exists():
        return stores_by_chain

    for chain_dir in FEEDS_DIR.iterdir():
        if not chain_dir.is_dir():
            continue

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            stores_by_chain[chain_dir.name].add(
                store_dir.name
            )

    return stores_by_chain


# ============================================================
# File discovery
# ============================================================

def discover_today_files(feed_type):
    """
    Discover today's files for one feed type.

    Expected local structure:

        data/feeds/{chain}/{store}/{feed_type}/...

    Subchains are NOT part of the local filesystem path.
    """
    today = date.today()

    files = []

    if not FEEDS_DIR.exists():
        return files

    for chain_dir in FEEDS_DIR.iterdir():
        if not chain_dir.is_dir():
            continue

        for store_dir in chain_dir.iterdir():
            if not store_dir.is_dir():
                continue

            feed_dir = store_dir / feed_type

            if not feed_dir.is_dir():
                continue

            for path in feed_dir.rglob("*"):
                if not path.is_file():
                    continue

                file_date = extract_date_from_filename(
                    path.name
                )

                if file_date != today:
                    continue

                files.append(
                    {
                        "path": path,
                        "chain": chain_dir.name,
                        "store": store_dir.name,
                        "feed_type": feed_type,
                        "size": path.stat().st_size,
                    }
                )

    return files


# ============================================================
# Group files by chain/store
# ============================================================

def group_by_store(files):
    grouped = defaultdict(list)

    for item in files:
        key = (
            item["chain"],
            item["store"],
        )

        grouped[key].append(item)

    return grouped


# ============================================================
# Build Full vs normal comparisons
# ============================================================

def build_comparisons(
    full_files,
    normal_files,
):
    """
    Compare Full and normal files belonging to the same
    chain/store.

    If multiple files exist for the same store, all
    combinations are checked.
    """
    full_grouped = group_by_store(full_files)
    normal_grouped = group_by_store(normal_files)

    all_stores = sorted(
        set(full_grouped) | set(normal_grouped)
    )

    comparisons = []

    for chain, store in all_stores:
        full_store_files = full_grouped.get(
            (chain, store),
            [],
        )

        normal_store_files = normal_grouped.get(
            (chain, store),
            [],
        )

        for full in full_store_files:
            for normal in normal_store_files:
                full_size = full["size"]
                normal_size = normal["size"]

                if full_size == 0:
                    ratio = None
                else:
                    ratio = normal_size / full_size

                suspicious = (
                    ratio is not None
                    and ratio >= SIZE_THRESHOLD
                )

                comparisons.append(
                    {
                        "chain": chain,
                        "store": store,
                        "full": full,
                        "normal": normal,
                        "full_size": full_size,
                        "normal_size": normal_size,
                        "ratio": ratio,
                        "suspicious": suspicious,
                    }
                )

    return comparisons


# ============================================================
# Overall summary
# ============================================================

def build_summary(
    full_files,
    normal_files,
    comparisons,
    store_folders_by_chain,
):
    full_stores = {
        (
            item["chain"],
            item["store"],
        )
        for item in full_files
    }

    normal_stores = {
        (
            item["chain"],
            item["store"],
        )
        for item in normal_files
    }

    common_stores = full_stores & normal_stores

    suspicious_comparisons = [
        comparison
        for comparison in comparisons
        if comparison["suspicious"]
    ]

    suspicious_stores = {
        (
            comparison["chain"],
            comparison["store"],
        )
        for comparison in suspicious_comparisons
    }

    total_stores = sum(
        len(stores)
        for stores in store_folders_by_chain.values()
    )

    suspicious_store_ratio = (
        len(suspicious_stores) / total_stores * 100
        if total_stores
        else 0
    )

    return {
        "total_stores": total_stores,
        "full_files": len(full_files),
        "normal_files": len(normal_files),
        "full_stores": len(full_stores),
        "normal_stores": len(normal_stores),
        "common_stores": len(common_stores),
        "comparisons": len(comparisons),
        "suspicious_comparisons": len(
            suspicious_comparisons
        ),
        "suspicious_stores": len(
            suspicious_stores
        ),
        "suspicious_store_ratio": round(
            suspicious_store_ratio,
            2,
        ),
        "stores_missing_full": len(
            normal_stores - full_stores
        ),
        "stores_missing_normal": len(
            full_stores - normal_stores
        ),
    }


# ============================================================
# Chain summary
# ============================================================

def build_chain_summary(
    full_files,
    normal_files,
    comparisons,
    store_folders_by_chain,
):
    full_stores_by_chain = defaultdict(set)
    normal_stores_by_chain = defaultdict(set)

    for item in full_files:
        full_stores_by_chain[
            item["chain"]
        ].add(item["store"])

    for item in normal_files:
        normal_stores_by_chain[
            item["chain"]
        ].add(item["store"])

    suspicious_stores_by_chain = defaultdict(set)
    suspicious_pairs_by_chain = defaultdict(int)

    for comparison in comparisons:
        if not comparison["suspicious"]:
            continue

        chain = comparison["chain"]
        store = comparison["store"]

        suspicious_stores_by_chain[
            chain
        ].add(store)

        suspicious_pairs_by_chain[
            chain
        ] += 1

    chains = sorted(
        set(store_folders_by_chain)
        | set(full_stores_by_chain)
        | set(normal_stores_by_chain)
    )

    summary = []

    for chain in chains:
        total_stores = len(
            store_folders_by_chain.get(
                chain,
                set(),
            )
        )

        full_stores = full_stores_by_chain.get(
            chain,
            set(),
        )

        normal_stores = normal_stores_by_chain.get(
            chain,
            set(),
        )

        checked_stores = (
            full_stores & normal_stores
        )

        suspicious_stores = (
            suspicious_stores_by_chain.get(
                chain,
                set(),
            )
        )

        suspicious_pairs = (
            suspicious_pairs_by_chain.get(
                chain,
                0,
            )
        )

        if not suspicious_stores:
            continue

        suspicious_ratio = (
            len(suspicious_stores)
            / total_stores
            * 100
            if total_stores
            else 0
        )

        summary.append(
            {
                "chain": chain,
                "stores": sorted(
                    suspicious_stores
                ),
                "total_stores": total_stores,
                "stores_checked": len(
                    checked_stores
                ),
                "suspicious_stores": len(
                    suspicious_stores
                ),
                "suspicious_store_ratio": round(
                    suspicious_ratio,
                    2,
                ),
                "suspicious_pairs": suspicious_pairs,
            }
        )

    summary.sort(
        key=lambda item: (
            -item["suspicious_store_ratio"],
            -item["suspicious_stores"],
        )
    )

    return summary

# ============================================================
# JSON helpers
# ============================================================

def serialize_comparison(comparison):
    """
    Convert an internal comparison object into JSON-safe data.
    """
    return {
        "chain": comparison["chain"],
        "store": comparison["store"],
        "ratio": (
            round(comparison["ratio"], 6)
            if comparison["ratio"] is not None
            else None
        ),
        "suspicious": comparison["suspicious"],
        "full": {
            "filename": comparison["full"]["path"].name,
            "path": str(
                comparison["full"]["path"].relative_to(
                    BASE_DIR
                )
            ),
            "size": comparison["full_size"],
        },
        "normal": {
            "filename": comparison["normal"]["path"].name,
            "path": str(
                comparison["normal"]["path"].relative_to(
                    BASE_DIR
                )
            ),
            "size": comparison["normal_size"],
        },
    }


# ============================================================
# Report
# ============================================================

def write_report(
    report_file,
    title,
    full_type,
    normal_type,
    full_files,
    normal_files,
    comparisons,
    store_folders_by_chain,
):
    summary = build_summary(
        full_files,
        normal_files,
        comparisons,
        store_folders_by_chain,
    )

    chain_summary = build_chain_summary(
        full_files,
        normal_files,
        comparisons,
        store_folders_by_chain,
    )

    suspicious = [
        comparison
        for comparison in comparisons
        if comparison["suspicious"]
    ]

    suspicious.sort(
        key=lambda item: (
            item["chain"],
            item["store"],
            item["full"]["path"].name,
            item["normal"]["path"].name,
        )
    )

    report = {
        "title": title,
        "date": date.today().isoformat(),
        "threshold": SIZE_THRESHOLD,
        "threshold_description": (
            "normal >= threshold * Full"
        ),
        "full_type": full_type,
        "normal_type": normal_type,
        "summary": summary,
        "by_chain": chain_summary,
        "suspicious": [
            serialize_comparison(
                comparison
            )
            for comparison in suspicious
        ],
    }

    with report_file.open(
        "w",
        encoding="utf-8",
    ) as output:
        json.dump(
            report,
            output,
            indent=2,
            ensure_ascii=False,
        )

        output.write("\n")


# ============================================================
# Main
# ============================================================

def main():
    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(f"Base directory:  {BASE_DIR}")
    print(f"Feeds directory: {FEEDS_DIR}")
    print(
        f"Today's date:    "
        f"{date.today().isoformat()}"
    )
    print()

    if not FEEDS_DIR.exists():
        print(
            f"ERROR: feeds directory does not exist:\n"
            f"  {FEEDS_DIR}"
        )
        return

    store_folders_by_chain = (
        discover_store_folders()
    )

    total_store_folders = sum(
        len(stores)
        for stores in store_folders_by_chain.values()
    )

    print(
        f"Store folders:  "
        f"{total_store_folders:,}"
    )

    # ========================================================
    # PRICES
    # ========================================================

    print("Checking prices vs pricesfull...")

    pricesfull = discover_today_files(
        "pricesfull"
    )

    prices = discover_today_files(
        "prices"
    )

    price_comparisons = build_comparisons(
        pricesfull,
        prices,
    )

    write_report(
        report_file=PRICES_REPORT,
        title="PRICES vs PRICESFULL INSPECTION",
        full_type="pricesfull",
        normal_type="prices",
        full_files=pricesfull,
        normal_files=prices,
        comparisons=price_comparisons,
        store_folders_by_chain=store_folders_by_chain,
    )

    price_suspicious = [
        comparison
        for comparison in price_comparisons
        if comparison["suspicious"]
    ]

    price_suspicious_stores = {
        (
            comparison["chain"],
            comparison["store"],
        )
        for comparison in price_suspicious
    }

    price_suspicious_ratio = (
        len(price_suspicious_stores)
        / total_store_folders
        * 100
        if total_store_folders
        else 0
    )

    print(
        f"  pricesfull files:   "
        f"{len(pricesfull):,}"
    )

    print(
        f"  prices files:       "
        f"{len(prices):,}"
    )

    print(
        f"  comparisons:        "
        f"{len(price_comparisons):,}"
    )

    print(
        f"  suspicious pairs:   "
        f"{len(price_suspicious):,}"
    )

    print(
        f"  suspicious stores:  "
        f"{len(price_suspicious_stores):,}"
    )

    print(
        f"  suspicious ratio:   "
        f"{price_suspicious_ratio:.2f}%"
    )

    print(
        f"  report: {PRICES_REPORT}"
    )

    print()

    # ========================================================
    # PROMOS
    # ========================================================

    print("Checking promos vs promofull...")

    promofull = discover_today_files(
        "promosfull"
    )

    promos = discover_today_files(
        "promos"
    )

    promo_comparisons = build_comparisons(
        promofull,
        promos,
    )

    write_report(
        report_file=PROMOS_REPORT,
        title="PROMOS vs PROMOFULL INSPECTION",
        full_type="promosfull",
        normal_type="promos",
        full_files=promofull,
        normal_files=promos,
        comparisons=promo_comparisons,
        store_folders_by_chain=store_folders_by_chain,
    )

    promo_suspicious = [
        comparison
        for comparison in promo_comparisons
        if comparison["suspicious"]
    ]

    promo_suspicious_stores = {
        (
            comparison["chain"],
            comparison["store"],
        )
        for comparison in promo_suspicious
    }

    promo_suspicious_ratio = (
        len(promo_suspicious_stores)
        / total_store_folders
        * 100
        if total_store_folders
        else 0
    )

    print(
        f"  promofull files:    "
        f"{len(promofull):,}"
    )

    print(
        f"  promos files:       "
        f"{len(promos):,}"
    )

    print(
        f"  comparisons:        "
        f"{len(promo_comparisons):,}"
    )

    print(
        f"  suspicious pairs:   "
        f"{len(promo_suspicious):,}"
    )

    print(
        f"  suspicious stores:  "
        f"{len(promo_suspicious_stores):,}"
    )

    print(
        f"  suspicious ratio:   "
        f"{promo_suspicious_ratio:.2f}%"
    )

    print(
        f"  report: {PROMOS_REPORT}"
    )

    print()

    # ========================================================
    # Final
    # ========================================================

    print("=" * 60)
    print("FULL VS NORMAL INSPECTION COMPLETE")
    print("=" * 60)

    print(
        f"Total store folders: "
        f"{total_store_folders:,}"
    )

    print(
        f"Prices suspicious ratio: "
        f"{price_suspicious_ratio:.2f}%"
    )

    print(
        f"Promos suspicious ratio:  "
        f"{promo_suspicious_ratio:.2f}%"
    )

    print(
        f"Prices report: {PRICES_REPORT}"
    )

    print(
        f"Promos report:  {PROMOS_REPORT}"
    )


if __name__ == "__main__":
    main()