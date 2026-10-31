
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "raw_product_pages" / "type_1"


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
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def json_path(path: str, key: Any) -> str:
    key = str(key)
    if key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def discover_structure(value: Any, path: str = "$"):
    """Yield JSON paths, types, and values, counting array items by index-independent paths."""
    yield path, value_type(value), value

    if isinstance(value, dict):
        for key, child in value.items():
            yield from discover_structure(child, json_path(path, key))

    elif isinstance(value, list):
        for child in value:
            yield from discover_structure(child, f"{path}[]")


def percentage(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "0.0%"


def add_example(collection: list[str], value: Any, limit: int) -> None:
    example = short_value(value)
    if example not in collection and len(collection) < limit:
        collection.append(example)


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
    errors: list[tuple[Path, str]] = []

    top_level_keys = Counter()
    path_presence = Counter()
    path_types: dict[str, Counter] = defaultdict(Counter)
    path_examples: dict[str, list[str]] = defaultdict(list)

    section_occurrences = Counter()
    section_content_types: dict[str, Counter] = defaultdict(Counter)
    section_examples: dict[str, list[str]] = defaultdict(list)
    section_content_keys: dict[str, Counter] = defaultdict(Counter)
    section_key_types: dict[str, dict[str, Counter]] = defaultdict(
        lambda: defaultdict(Counter)
    )

    object_key_presence: dict[str, Counter] = defaultdict(Counter)
    object_key_types: dict[str, dict[str, Counter]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    object_examples: dict[str, list[str]] = defaultdict(list)

    value_patterns: dict[str, Counter] = defaultdict(Counter)
    value_examples: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    anomalies = Counter()
    anomaly_examples: dict[str, list[str]] = defaultdict(list)
    full_examples: list[tuple[str, str]] = []

    image_stats = Counter()
    image_examples: dict[str, list[str]] = defaultdict(list)

    def record_anomaly(kind: str, file: Path, detail: str) -> None:
        anomalies[kind] += 1
        add_example(
            anomaly_examples[kind],
            {"file": str(file.relative_to(input_dir)), "detail": detail},
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
        relative_file = str(file.relative_to(input_dir))

        if not isinstance(data, dict):
            record_anomaly("top_level_not_object", file, value_type(data))
            add_example(
                full_examples,
                {"file": relative_file, "data": data},
                max_full_examples,
            )
            continue

        top_level_keys.update(data.keys())

        if len(full_examples) < max_full_examples:
            full_examples.append(
                (relative_file, json.dumps(data, ensure_ascii=False, indent=2))
            )

        for key in (
            "item_code", "source", "url", "scraped_at",
            "page_code", "name", "images", "sections",
        ):
            if key not in data:
                record_anomaly("missing_top_level_field", file, key)
            elif data[key] is None or data[key] == "":
                record_anomaly("empty_top_level_field", file, key)

        for path, kind, value in discover_structure(data):
            path_types[path][kind] += 1
            add_example(path_examples[path], value, examples_per_group)

        # Count path presence once per file, rather than once per repeated array item.
        file_paths = {
            path
            for path, _, _ in discover_structure(data)
        }
        path_presence.update(file_paths)

        # Inspect every object recursively for key presence, types, and value patterns.
        for path, kind, value in discover_structure(data):
            if kind != "object":
                continue

            for key, child in value.items():
                object_key_presence[path][key] += 1
                object_key_types[path][key][value_type(child)] += 1

        for path, kind, value in discover_structure(data):
            if kind not in ("string", "number", "null", "bool"):
                continue

            if value is None:
                pattern = "null"
            elif isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    pattern = "empty_string"
                elif stripped.lower() in {"null", "none", "n/a", "לא ידוע"}:
                    pattern = "placeholder_string"
                elif stripped.startswith("<") and stripped.endswith(">"):
                    pattern = "html_like"
                elif stripped.replace(",", ".", 1).replace("-", "", 1).isdigit():
                    pattern = "numeric_string"
                elif any(mark in stripped.lower() for mark in ("http://", "https://")):
                    pattern = "url_like"
                else:
                    pattern = "nonempty_string"
            elif isinstance(value, bool):
                pattern = "boolean"
            else:
                pattern = "number"

            value_patterns[path][pattern] += 1
            add_example(
                value_examples[path][pattern],
                value,
                examples_per_group,
            )

        # Images
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
                    add_example(image_examples["non_string"], image, examples_per_group)
                elif not image.strip():
                    image_stats["empty_strings"] += 1
                elif any(
                    marker in image.lower()
                    for marker in ("default", "placeholder", "no-image", "no_image")
                ):
                    image_stats["possible_placeholder_images"] += 1
                    add_example(image_examples["possible_placeholder"], image, examples_per_group)

        # Sections
        sections = data.get("sections")
        if not isinstance(sections, list):
            record_anomaly("sections_not_array", file, value_type(sections))
            continue

        if not sections:
            record_anomaly("empty_sections_array", file, "sections is empty")

        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                record_anomaly(
                    "section_not_object", file,
                    f"sections[{index}] is {value_type(section)}",
                )
                continue

            title = str(section.get("title", "<missing title>"))
            content = section.get("content")
            content_kind = value_type(content)
            group = f"{title} [content={content_kind}]"

            section_occurrences[title] += 1
            section_content_types[title][content_kind] += 1
            add_example(
                section_examples[group],
                {
                    "file": relative_file,
                    "section": section,
                },
                examples_per_group,
            )

            if "title" not in section:
                record_anomaly("section_missing_title", file, f"index={index}")
            if "content" not in section:
                record_anomaly("section_missing_content", file, f"title={title}")

            if isinstance(content, dict):
                for key, child in content.items():
                    section_content_keys[title][key] += 1
                    section_key_types[title][key][value_type(child)] += 1

        # Common product-specific objects.
        details = data.get("product_details")
        if "product_details" in data and not isinstance(details, dict):
            record_anomaly(
                "product_details_not_object", file, value_type(details)
            )

        if isinstance(details, dict):
            for key, value in details.items():
                if value is None or value == "" or value == [] or value == {}:
                    record_anomaly(
                        "empty_product_detail",
                        file,
                        f"{key}={short_value(value)}",
                    )

    total_discovered = len(files)
    lines = [
        "TYPE_1 PRODUCT PAGE INSPECTION REPORT",
        "=" * 80,
        f"Input directory: {input_dir}",
        f"Files discovered: {total_discovered}",
        f"Valid JSON files: {valid_files}",
        f"Invalid/unreadable files: {len(errors)}",
        f"Files skipped by --limit: not applicable" if limit is None else
        f"Limit requested: {limit}",
        "",
        "Counts for JSON paths/types are occurrences, unless explicitly marked per file.",
        "Section counts are occurrences across all products.",
    ]

    def heading(title: str) -> None:
        lines.extend(["", "=" * 80, title.upper(), "=" * 80])

    heading("Top-level fields")
    lines.append("Field | Files containing field | Percentage")
    for key, count in top_level_keys.most_common():
        lines.append(
            f"{key} | {count}/{valid_files} | {percentage(count, valid_files)}"
        )

    heading("JSON paths and observed types")
    lines.append("Presence is counted once per file; type counts are occurrences.")
    for path in sorted(
        path_types,
        key=lambda item: (item.count(".") + item.count("[]"), item),
    ):
        count = path_presence[path]
        types = ", ".join(
            f"{kind}={n}"
            for kind, n in path_types[path].most_common()
        )
        lines.extend([
            f"\n{path}",
            f"  Files present: {count}/{valid_files} ({percentage(count, valid_files)})",
            f"  Types: {types}",
            f"  Examples: {' | '.join(path_examples[path])}",
        ])

    heading("Section title and content type matrix")
    lines.append("Title | Occurrences | Content types")
    for title, count in section_occurrences.most_common():
        types = ", ".join(
            f"{kind}={n}"
            for kind, n in section_content_types[title].most_common()
        )
        lines.append(f"{title} | {count} | {types}")

    heading("Section content object keys")
    lines.append(
        "For each section title, keys are counted across occurrences where content is an object."
    )
    for title in section_occurrences:
        if not section_content_keys[title]:
            continue
        lines.append(f"\n[{title}]")
        for key, count in section_content_keys[title].most_common():
            types = ", ".join(
                f"{kind}={n}"
                for kind, n in section_key_types[title][key].most_common()
            )
            lines.append(f"  {key}: {count}; types: {types}")

    heading("Representative section examples")
    for group, examples in sorted(section_examples.items()):
        lines.append(f"\n[{group}]")
        for example in examples:
            lines.append(f"  {example}")

    heading("Nested object key profiles")
    for object_path in sorted(object_key_presence):
        keys = object_key_presence[object_path]
        lines.append(f"\n[{object_path}]")
        lines.append(f"  Objects observed: {sum(keys.values())}")
        for key, count in keys.most_common():
            types = ", ".join(
                f"{kind}={n}"
                for kind, n in object_key_types[object_path][key].most_common()
            )
            lines.append(f"  {key}: {count}; types: {types}")

    heading("Value patterns")
    lines.append(
        "Heuristic classifications only; these identify candidates for manual inspection."
    )
    for path in sorted(value_patterns):
        lines.append(f"\n[{path}]")
        for pattern, count in value_patterns[path].most_common():
            examples = value_examples[path][pattern]
            lines.append(
                f"  {pattern}: {count}; examples: {' | '.join(short_value(e) for e in examples)}"
            )

    heading("Images")
    for key, count in image_stats.most_common():
        lines.append(f"{key}: {count}")
    for kind, examples in image_examples.items():
        lines.append(f"  {kind} examples: {' | '.join(examples)}")

    heading("Detected anomalies")
    if not anomalies:
        lines.append("No anomalies detected by the current checks.")
    else:
        for kind, count in anomalies.most_common():
            lines.append(f"\n{kind}: {count}")
            for example in anomaly_examples[kind]:
                lines.append(f"  {example}")

    heading("Invalid/unreadable JSON files")
    if not errors:
        lines.append("None.")
    else:
        for file, error in errors:
            lines.append(f"{file.relative_to(input_dir)}: {error}")

    heading("Representative complete product JSON files")
    lines.append(
        "These are complete source records, useful for inspecting uncommon combinations."
    )
    for relative_file, raw_json in full_examples:
        lines.append(f"\n--- {relative_file} ---")
        lines.append(raw_json)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Comprehensively profile scraped type_1 product JSON files "
            "to reveal schema variations before parser implementation."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Directory containing JSON files; searched recursively.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Inspect only the first N JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional report output path.",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=3,
        help="Maximum representative examples per group (default: 3).",
    )
    parser.add_argument(
        "--full-examples",
        type=int,
        default=10,
        help="Maximum complete product records included (default: 10).",
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

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"Report saved to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
