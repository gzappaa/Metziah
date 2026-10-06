"""Inspect parsed product image URLs across all parsed companies."""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


PARSED_DIR = Path("data/parsed")
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
REPORT_PATH = REPORT_DIR / "images_parsed.txt"

NUMBER_RE = re.compile(r"^\d+$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
GS1_RE = re.compile(r"^(\d+)-(\d+)$")
TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")


def normalize_segment(segment: str) -> str:
    if not segment:
        return segment

    template = TEMPLATE_RE.fullmatch(segment)

    if template:
        value = template.group(1)

        if "||" in value:
            value = value.split("||", 1)[0]

        return f"{{{value}}}"

    if TIMESTAMP_RE.match(segment):
        return "{timestamp}"

    if GS1_RE.match(segment):
        return "{barcode}-{supplier_id}"

    if NUMBER_RE.fullmatch(segment):
        return "{number}"

    return segment


def normalize_filename(filename: str) -> str:
    if "." not in filename:
        return normalize_segment(filename)

    name, extension = filename.rsplit(".", 1)

    name = normalize_segment(name)
    extension = normalize_segment(extension)

    return f"{name}.{extension}"


def normalize_url_structure(url: str) -> str:
    path = urlparse(url).path

    segments = [
        segment
        for segment in path.split("/")
        if segment
    ]

    if not segments:
        return "/"

    normalized = []

    for index, segment in enumerate(segments):
        if index == len(segments) - 1:
            normalized.append(
                normalize_filename(segment)
            )
        else:
            normalized.append(
                normalize_segment(segment)
            )

    return "/" + "/".join(normalized)


def exact_value_in_url(
    url: str,
    value: object,
) -> bool:
    if not url or value in (None, ""):
        return False

    value = str(value)

    return bool(
        re.search(
            rf"(?<!\d){re.escape(value)}(?!\d)",
            url,
        )
    )


def extract_gs1_barcode(url: str) -> str | None:
    match = re.search(
        r"/gs1-products/[^/]+/[^/]+/(\d+)-\d+/",
        url,
    )

    if match:
        return match.group(1)

    return None


def extract_extension(url: str) -> str:
    path = urlparse(url).path

    if "." not in path:
        return "(none)"

    extension = path.rsplit(".", 1)[1]

    template = TEMPLATE_RE.fullmatch(extension)

    if template:
        value = template.group(1)

        if "||" in value:
            value = value.split("||", 1)[0]

        return f"{{{value}}}"

    return extension.lower()


def inspect_company(
    company: str,
    company_dir: Path,
) -> dict:
    stats = {
        "company": company,
        "files": 0,
        "records": 0,
        "products_with_main_image": 0,
        "products_with_images_url": 0,
        "products_with_any_image": 0,
        "main_image_urls": 0,
        "image_urls": 0,
        "barcode_matches": 0,
        "barcode_misses": 0,
        "barcode_unavailable": 0,
        "product_id_matches": 0,
        "product_id_misses": 0,
        "product_id_unavailable": 0,
        "gs1_barcode_matches": 0,
        "gs1_barcode_mismatches": 0,
        "structures": Counter(),
        "extensions": Counter(),
    }

    files = sorted(company_dir.glob("*.jsonl"))

    stats["files"] = len(files)

    for parsed_file in files:
        with parsed_file.open(
            encoding="utf-8"
        ) as f:
            for line in f:
                line = line.strip()

                if not line:
                    continue

                try:
                    product = json.loads(line)
                except json.JSONDecodeError:
                    continue

                stats["records"] += 1

                barcode = product.get("barcode")
                product_id = product.get("product_id")

                urls = []

                main_url = product.get(
                    "main_image_url"
                )

                if main_url:
                    stats[
                        "products_with_main_image"
                    ] += 1

                    stats["main_image_urls"] += 1
                    urls.append(main_url)

                image_urls = []

                for image in product.get("images") or []:
                    if not isinstance(image, dict):
                        continue

                    url = image.get("url")

                    if url:
                        image_urls.append(url)
                        urls.append(url)

                if image_urls:
                    stats[
                        "products_with_images_url"
                    ] += 1

                if urls:
                    stats[
                        "products_with_any_image"
                    ] += 1

                for url in urls:
                    stats["image_urls"] += 1

                    stats["structures"][
                        normalize_url_structure(url)
                    ] += 1

                    stats["extensions"][
                        extract_extension(url)
                    ] += 1

                    if barcode is None:
                        stats[
                            "barcode_unavailable"
                        ] += 1
                    elif exact_value_in_url(
                        url,
                        barcode,
                    ):
                        stats[
                            "barcode_matches"
                        ] += 1
                    else:
                        stats[
                            "barcode_misses"
                        ] += 1

                    if product_id is None:
                        stats[
                            "product_id_unavailable"
                        ] += 1
                    elif exact_value_in_url(
                        url,
                        product_id,
                    ):
                        stats[
                            "product_id_matches"
                        ] += 1
                    else:
                        stats[
                            "product_id_misses"
                        ] += 1

                    gs1_barcode = (
                        extract_gs1_barcode(url)
                    )

                    if gs1_barcode:
                        if gs1_barcode == str(
                            barcode
                        ):
                            stats[
                                "gs1_barcode_matches"
                            ] += 1
                        else:
                            stats[
                                "gs1_barcode_mismatches"
                            ] += 1

    return stats


def write_company_report(
    f,
    stats: dict,
) -> None:
    f.write(
        f"{stats['company'].upper()}\n"
    )
    f.write("=" * 100 + "\n\n")

    f.write(
        f"JSONL files: "
        f"{stats['files']:,}\n"
    )
    f.write(
        f"Records: "
        f"{stats['records']:,}\n"
    )
    f.write(
        f"Products with main_image_url: "
        f"{stats['products_with_main_image']:,}\n"
    )
    f.write(
        f"Products with images[].url: "
        f"{stats['products_with_images_url']:,}\n"
    )
    f.write(
        f"Products with any image URL: "
        f"{stats['products_with_any_image']:,}\n"
    )
    f.write(
        f"main_image_url occurrences: "
        f"{stats['main_image_urls']:,}\n"
    )
    f.write(
        f"images[].url occurrences: "
        f"{stats['image_urls']:,}\n"
    )
    f.write("\n")

    f.write("Barcode in Image URL\n")
    f.write("-" * 100 + "\n")
    f.write(
        f"Present: "
        f"{stats['barcode_matches']:,}\n"
    )
    f.write(
        f"Absent: "
        f"{stats['barcode_misses']:,}\n"
    )
    f.write(
        f"Unavailable: "
        f"{stats['barcode_unavailable']:,}\n"
    )
    f.write("\n")

    f.write("Product ID in Image URL\n")
    f.write("-" * 100 + "\n")
    f.write(
        f"Present: "
        f"{stats['product_id_matches']:,}\n"
    )
    f.write(
        f"Absent: "
        f"{stats['product_id_misses']:,}\n"
    )
    f.write(
        f"Unavailable: "
        f"{stats['product_id_unavailable']:,}\n"
    )
    f.write("\n")

    f.write("GS1 Barcode Relationship\n")
    f.write("-" * 100 + "\n")
    f.write(
        f"Matches product barcode: "
        f"{stats['gs1_barcode_matches']:,}\n"
    )
    f.write(
        f"Differs from product barcode: "
        f"{stats['gs1_barcode_mismatches']:,}\n"
    )
    f.write("\n")

    f.write("Extensions\n")
    f.write("-" * 100 + "\n")

    for extension, count in (
        stats["extensions"].most_common()
    ):
        f.write(
            f"{count:>10,}  {extension}\n"
        )

    f.write("\n")

    f.write("Normalized URL Structures\n")
    f.write("-" * 100 + "\n")

    for structure, count in (
        stats["structures"].most_common()
    ):
        f.write(
            f"{count:>10,}  {structure}\n"
        )

    f.write("\n\n")


def write_report(
    all_stats: list[dict],
) -> None:
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as f:
        f.write(
            "Parsed Product Images Inspection\n"
        )
        f.write("=" * 100 + "\n\n")

        for stats in all_stats:
            write_company_report(
                f,
                stats,
            )

    print(
        f"Report written to: {REPORT_PATH}"
    )

    for stats in all_stats:
        print(
            f"{stats['company']}: "
            f"{stats['records']:,} records, "
            f"{stats['image_urls']:,} image URLs"
        )


def main() -> None:
    all_stats = [
        inspect_company(
            company_dir.name,
            company_dir,
        )
        for company_dir in sorted(
            PARSED_DIR.iterdir()
        )
        if company_dir.is_dir()
    ]

    write_report(all_stats)


if __name__ == "__main__":
    main()