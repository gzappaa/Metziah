"""
Profile raw type_2 product-page JSON files.

Usage:
    python -m utils.processing.profile_type2
    python -m utils.processing.profile_type2 --limit 100
    python -m utils.processing.profile_type2 --output reports/custom_report.txt
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "raw_product_pages" / "type_2"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "reports" / "type2_profile.txt"

def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def short_value(value: Any, limit: int = 180) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def json_path(path: str, key: Any) -> str:
    key = str(key)
    if key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def discover_structure(value: Any, path: str = "$"):
    """Yield each JSON path, type, and value. Array indices are omitted."""
    yield path, value_type(value), value

    if isinstance(value, dict):
        for key, child in value.items():
            yield from discover_structure(child, json_path(path, key))
    elif isinstance(value, list):
        for child in value:
            yield from discover_structure(child, f"{path}[]")


def percentage(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "0.0%"


def add_example(examples: list[str], value: Any, limit: int) -> None:
    example = short_value(value)
    if example not in examples and len(examples) < limit:
        examples.append(example)


def inspect_files(
    input_dir: Path,
    limit: int | None = None,
    examples_per_group: int = 3,
    max_full_examples: int = 10,
) -> str:
    files = sorted(input_dir.rglob("*.json"))

    if limit is not None:
        files = files[:limit]

    if not files:
        raise SystemExit(f"No JSON files found in {input_dir}")

    valid_files = 0
    errors = []
    top_level_keys = Counter()
    path_presence = Counter()
    path_types = defaultdict(Counter)
    path_examples = defaultdict(list)
    object_key_presence = defaultdict(Counter)
    object_key_types = defaultdict(lambda: defaultdict(Counter))
    value_patterns = defaultdict(Counter)
    value_examples = defaultdict(lambda: defaultdict(list))
    anomalies = Counter()
    anomaly_examples = defaultdict(list)
    full_examples = []
    image_stats = Counter()
    image_examples = defaultdict(list)

    def record_anomaly(kind: str, file: Path, detail: str) -> None:
        anomalies[kind] += 1
        add_example(
            anomaly_examples[kind],
            {
                "file": str(file.relative_to(input_dir)),
                "detail": detail,
            },
            examples_per_group,
        )

    for file in files:
        try:
            with file.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append((file, str(exc)))
            continue

        valid_files += 1

        if not isinstance(data, dict):
            record_anomaly("top_level_not_object", file, value_type(data))
            continue

        top_level_keys.update(data.keys())

        if len(full_examples) < max_full_examples:
            full_examples.append(
                (
                    str(file.relative_to(input_dir)),
                    json.dumps(data, ensure_ascii=False, indent=2),
                )
            )

        expected_fields = (
            "item_code",
            "source",
            "url",
            "scraped_at",
            "page_code",
            "name",
            "images",
            "details",
        )

        for key in expected_fields:
            if key not in data:
                record_anomaly("missing_top_level_field", file, key)
            elif data[key] is None or data[key] == "":
                record_anomaly("empty_top_level_field", file, key)

        details = data.get("details")

        if not isinstance(details, dict):
            record_anomaly(
                "details_not_object",
                file,
                value_type(details),
            )

        structure = list(discover_structure(data))
        paths_in_file = set()

        for path, kind, value in structure:
            path_types[path][kind] += 1
            paths_in_file.add(path)
            add_example(path_examples[path], value, examples_per_group)

        path_presence.update(paths_in_file)

        for path, kind, value in structure:
            if kind == "object":
                for key, child in value.items():
                    object_key_presence[path][key] += 1
                    object_key_types[path][key][value_type(child)] += 1

            if kind not in ("string", "number", "null", "bool"):
                continue

            if value is None:
                pattern = "null"
            elif isinstance(value, bool):
                pattern = "boolean"
            elif isinstance(value, (int, float)):
                pattern = "number"
            elif not value.strip():
                pattern = "empty_string"
            elif value.strip().lower() in {
                "null",
                "none",
                "n/a",
                "לא ידוע",
            }:
                pattern = "placeholder_string"
            elif value.strip().startswith(("http://", "https://")):
                pattern = "url_like"
            elif (
                value.strip()
                .replace(",", ".", 1)
                .replace("-", "", 1)
                .isdigit()
            ):
                pattern = "numeric_string"
            else:
                pattern = "nonempty_string"

            value_patterns[path][pattern] += 1
            add_example(
                value_examples[path][pattern],
                value,
                examples_per_group,
            )

        # Top-level images should normally be an array of URL strings.
        images = data.get("images")

        if not isinstance(images, list):
            image_stats["images_not_array"] += 1
            record_anomaly("images_not_array", file, value_type(images))
        else:
            if not images:
                image_stats["empty_array"] += 1

            image_stats["total_entries"] += len(images)

            for image in images:
                if not isinstance(image, str):
                    image_stats["non_string_entries"] += 1
                    add_example(
                        image_examples["non_string"],
                        image,
                        examples_per_group,
                    )
                elif not image.strip():
                    image_stats["empty_strings"] += 1
                elif any(
                    marker in image.lower()
                    for marker in (
                        "default",
                        "placeholder",
                        "no-image",
                        "no_image",
                    )
                ):
                    image_stats["possible_placeholder_images"] += 1
                    add_example(
                        image_examples["possible_placeholder"],
                        image,
                        examples_per_group,
                    )

        # details.images is a separate object containing named image paths.
        if isinstance(details, dict):
            detail_images = details.get("images")

            if detail_images is not None and not isinstance(
                detail_images, dict
            ):
                record_anomaly(
                    "details_images_not_object",
                    file,
                    value_type(detail_images),
                )

        for key in ("item_code", "page_code", "name", "source"):
            value = data.get(key)

            if value is None or (
                isinstance(value, str) and not value.strip()
            ):
                record_anomaly("missing_or_empty_identifier", file, key)

        if isinstance(details, dict):
            for key in (
                "barcode",
                "price",
                "department",
                "group",
                "subGroup",
                "gs",
            ):
                if key not in details:
                    record_anomaly("missing_details_field", file, key)

    lines = [
        "TYPE_2 PRODUCT PAGE PROFILING REPORT",
        "=" * 80,
        f"Input directory: {input_dir}",
        f"Files discovered: {len(files)}",
        f"Valid JSON files: {valid_files}",
        f"Invalid/unreadable files: {len(errors)}",
        "Path presence counts files; type counts count occurrences.",
    ]

    def heading(title: str) -> None:
        lines.extend(["", "=" * 80, title.upper(), "=" * 80])

    heading("Top-level fields")
    lines.append("Field | Files containing field | Percentage")

    for key, count in top_level_keys.most_common():
        lines.append(
            f"{key} | {count}/{valid_files} | "
            f"{percentage(count, valid_files)}"
        )

    heading("JSON paths and observed types")

    for path in sorted(
        path_types,
        key=lambda item: (item.count(".") + item.count("[]"), item),
    ):
        count = path_presence[path]
        types = ", ".join(
            f"{kind}={number}"
            for kind, number in path_types[path].most_common()
        )

        lines.extend(
            [
                f"\n{path}",
                f"  Files present: {count}/{valid_files} "
                f"({percentage(count, valid_files)})",
                f"  Types: {types}",
                f"  Examples: {' | '.join(path_examples[path])}",
            ]
        )

    heading("Nested object key profiles")

    for object_path in sorted(object_key_presence):
        keys = object_key_presence[object_path]
        lines.append(f"\n[{object_path}]")

        for key, count in keys.most_common():
            types = ", ".join(
                f"{kind}={number}"
                for kind, number in (
                    object_key_types[object_path][key].most_common()
                )
            )
            lines.append(f"  {key}: {count}; types: {types}")

    heading("Value patterns")
    lines.append(
        "Classifications are heuristic; verify examples before relying on them."
    )

    for path in sorted(value_patterns):
        lines.append(f"\n[{path}]")

        for pattern, count in value_patterns[path].most_common():
            examples = value_examples[path][pattern]
            lines.append(
                f"  {pattern}: {count}; examples: "
                f"{' | '.join(examples)}"
            )

    heading("Image analysis")

    for key, count in image_stats.most_common():
        lines.append(f"{key}: {count}")

    for kind, examples in image_examples.items():
        lines.append(f"{kind} examples: {' | '.join(examples)}")

    heading("Detected anomalies")

    if not anomalies:
        lines.append("No anomalies detected by the current checks.")
    else:
        for kind, count in anomalies.most_common():
            lines.append(f"\n{kind}: {count}")

            for example in anomaly_examples[kind]:
                lines.append(f"  {example}")

    heading("Invalid or unreadable JSON files")

    if not errors:
        lines.append("None.")
    else:
        for file, error in errors:
            lines.append(f"{file.relative_to(input_dir)}: {error}")

    heading("Representative complete records")

    for relative_file, raw_json in full_examples:
        lines.append(f"\n--- {relative_file} ---")
        lines.append(raw_json)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile type_2 product-page JSON files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input directory (searched recursively).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Inspect only the first N JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Report path (default: {DEFAULT_OUTPUT.relative_to(ROOT)}).",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=3,
        help="Maximum examples per group.",
    )
    parser.add_argument(
        "--full-examples",
        type=int,
        default=10,
        help="Maximum complete JSON records included in the report.",
    )

    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be greater than 0")

    if args.examples < 0 or args.full_examples < 0:
        parser.error("--examples and --full-examples cannot be negative")

    report = inspect_files(
        args.input,
        limit=args.limit,
        examples_per_group=args.examples,
        max_full_examples=args.full_examples,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report + "\n", encoding="utf-8")

    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()