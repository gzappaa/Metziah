import io
import json
from unittest.mock import Mock
from unittest.mock import MagicMock, Mock
import httpx
import pytest
from PIL import Image

from utils.processing import download_img as downloader


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def make_image_bytes(image_format="JPEG"):
    image = Image.effect_noise((100, 100), 100).convert("RGB")

    output = io.BytesIO()
    image.save(output, format=image_format)

    return output.getvalue()


def make_response(
    content=b"",
    status_code=200,
):
    return httpx.Response(
        status_code=status_code,
        content=content,
        request=httpx.Request(
            "GET",
            "https://example.com/image.jpg",
        ),
    )


def read_image(path):
    with Image.open(path) as image:
        image.load()
        return image


# ---------------------------------------------------------------------
# record_item_code
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"item_code": "123"}, "123"),
        ({"barcode": "456"}, "456"),
        ({"ean": "789"}, "789"),
        ({"gtin": "111"}, "111"),
        ({"itemCode": "222"}, "222"),
        (
            {
                "item_code": None,
                "barcode": "456",
            },
            "456",
        ),
        (
            {
                "item_code": " ",
                "barcode": "456",
            },
            "456",
        ),
        ({"item_code": " 123 "}, "123"),
        ({}, None),
    ],
)
def test_record_item_code(record, expected):
    assert downloader.record_item_code(record) == expected


def test_record_item_code_respects_key_priority():
    record = {
        "item_code": "111",
        "barcode": "222",
        "ean": "333",
    }

    assert downloader.record_item_code(record) == "111"


# ---------------------------------------------------------------------
# image_urls
# ---------------------------------------------------------------------

def test_image_urls_extracts_supported_fields():
    record = {
        "main_image_url": " https://example.com/1.jpg ",
        "image_url": "https://example.com/2.jpg",
        "image": {
            "url": "https://example.com/3.jpg",
        },
        "images": [
            "https://example.com/4.jpg",
            {
                "url": "https://example.com/5.jpg",
            },
        ],
    }

    assert downloader.image_urls(record) == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
        "https://example.com/3.jpg",
        "https://example.com/4.jpg",
        "https://example.com/5.jpg",
    ]


def test_image_urls_removes_duplicates():
    record = {
        "main_image_url": "https://example.com/1.jpg",
        "image_url": "https://example.com/1.jpg",
        "images": [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
        ],
    }

    assert downloader.image_urls(record) == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
    ]


def test_image_urls_ignores_invalid_values():
    record = {
        "main_image_url": None,
        "image_url": 123,
        "image": {},
        "images": [
            None,
            123,
            {},
            {"url": ""},
            {"url": 123},
            " ",
        ],
    }

    assert downloader.image_urls(record) == []


def test_image_urls_handles_missing_fields():
    assert downloader.image_urls({}) == []


# ---------------------------------------------------------------------
# iter_parsed_records
# ---------------------------------------------------------------------

def test_iter_parsed_records_reads_jsonl_files(
    tmp_path,
    monkeypatch,
):
    parsed_dir = tmp_path / "parsed"

    company_a = parsed_dir / "company_a"
    company_b = parsed_dir / "company_b"

    company_a.mkdir(parents=True)
    company_b.mkdir(parents=True)

    file_a = company_a / "products.jsonl"
    file_b = company_b / "products.jsonl"

    file_a.write_text(
        '\n'
        '{"barcode": "111"}\n'
        '{"barcode": "222"}\n',
        encoding="utf-8",
    )

    file_b.write_text(
        '{"barcode": "333"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        downloader,
        "PARSED_DIR",
        parsed_dir,
    )

    records = list(downloader.iter_parsed_records())

    assert [record["barcode"] for _, record in records] == [
        "111",
        "222",
        "333",
    ]


def test_iter_parsed_records_skips_invalid_lines(
    tmp_path,
    monkeypatch,
):
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()

    file = parsed_dir / "products.jsonl"

    file.write_text(
        '{"barcode": "111"}\n'
        'invalid json\n'
        '\n'
        '["not", "a", "dict"]\n'
        '{"barcode": "222"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        downloader,
        "PARSED_DIR",
        parsed_dir,
    )

    records = list(downloader.iter_parsed_records())

    assert [record["barcode"] for _, record in records] == [
        "111",
        "222",
    ]


def test_iter_parsed_records_returns_nothing_when_directory_missing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "PARSED_DIR",
        tmp_path / "missing",
    )

    assert list(downloader.iter_parsed_records()) == []


# ---------------------------------------------------------------------
# collect_image_candidates
# ---------------------------------------------------------------------

def test_collect_image_candidates_aggregates_across_sources(
    monkeypatch,
):
    records = [
        (
            None,
            {
                "barcode": "111",
                "image_url": "https://example.com/1.jpg",
            },
        ),
        (
            None,
            {
                "item_code": "111",
                "images": [
                    "https://example.com/2.jpg",
                    "https://example.com/1.jpg",
                ],
            },
        ),
        (
            None,
            {
                "barcode": "222",
                "image_url": "https://example.com/3.jpg",
            },
        ),
    ]

    monkeypatch.setattr(
        downloader,
        "iter_parsed_records",
        lambda: iter(records),
    )

    result = downloader.collect_image_candidates(
        {"111", "333"},
    )

    assert result == {
        "111": [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
        ],
        "333": [],
    }


def test_collect_image_candidates_returns_empty_lists_for_missing_codes(
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "iter_parsed_records",
        lambda: iter([]),
    )

    assert downloader.collect_image_candidates(
        {"111", "222"},
    ) == {
        "111": [],
        "222": [],
    }


# ---------------------------------------------------------------------
# expand_url_template
# ---------------------------------------------------------------------

def test_expand_url_template_without_template():
    url = "https://example.com/image.jpg"

    assert downloader.expand_url_template(url) == [url]


def test_expand_url_template_expands_size_and_extension():
    result = downloader.expand_url_template(
        "https://example.com/image_{{size}}.{{extension}}"
    )

    assert len(result) == (
        len(downloader.TEMPLATE_SIZES)
        * len(downloader.TEMPLATE_EXTENSIONS)
    )

    assert result[0] == (
        "https://example.com/image_large.jpg"
    )

    assert result[-1] == (
        "https://example.com/image_original.webp"
    )


@pytest.mark.parametrize(
    "template",
    [
        "{{extension}}",
        "{{ extension }}",
        "{{extension || 'jpg'}}",
        "{{ extension || 'png' }}",
    ],
)
def test_expand_url_template_supports_extension_variants(template):
    result = downloader.expand_url_template(
        f"https://example.com/image.{template}"
    )

    assert result
    assert all("{{" not in url for url in result)
    assert all("}}" not in url for url in result)


def test_expand_url_template_does_not_return_unresolved_templates():
    result = downloader.expand_url_template(
        "https://example.com/{{unknown}}.jpg"
    )

    assert result == []


# ---------------------------------------------------------------------
# all_url_attempts
# ---------------------------------------------------------------------

def test_all_url_attempts_preserves_order_and_removes_duplicates():
    result = downloader.all_url_attempts(
        [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
            "https://example.com/1.jpg",
        ]
    )

    assert result == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
    ]


def test_all_url_attempts_expands_templates():
    result = downloader.all_url_attempts(
        [
            "https://example.com/image.jpg",
            "https://example.com/{{size}}.{{extension}}",
        ]
    )

    assert result[0] == "https://example.com/image.jpg"
    assert len(result) == (
        1
        + len(downloader.TEMPLATE_SIZES)
        * len(downloader.TEMPLATE_EXTENSIONS)
    )


# ---------------------------------------------------------------------
# image_bytes_to_jpeg
# ---------------------------------------------------------------------

def test_image_bytes_to_jpeg_converts_jpeg():
    data = make_image_bytes("JPEG")

    result = downloader.image_bytes_to_jpeg(data)

    assert result is not None

    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


@pytest.mark.parametrize(
    "image_format",
    ["PNG", "WEBP"],
)
def test_image_bytes_to_jpeg_converts_other_formats(image_format):
    data = make_image_bytes(image_format)

    result = downloader.image_bytes_to_jpeg(data)

    assert result is not None

    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_image_bytes_to_jpeg_rejects_small_files():
    assert downloader.image_bytes_to_jpeg(b"small") is None


def test_image_bytes_to_jpeg_rejects_invalid_data():
    data = b"x" * downloader.MIN_IMAGE_BYTES

    assert downloader.image_bytes_to_jpeg(data) is None


def test_image_bytes_to_jpeg_rejects_tiny_dimensions():
    output = io.BytesIO()

    Image.new("RGB", (1, 1)).save(
        output,
        format="JPEG",
    )

    # Pad the data to pass the minimum byte check.
    data = output.getvalue() + b" " * downloader.MIN_IMAGE_BYTES

    assert downloader.image_bytes_to_jpeg(data) is None


def test_image_bytes_to_jpeg_handles_transparency():
    image = Image.effect_noise((100, 100), 100).convert("RGBA")

    # Make the center pixel fully transparent.
    image.putpixel((50, 50), (255, 0, 0, 0))

    output = io.BytesIO()
    image.save(output, format="PNG")

    result = downloader.image_bytes_to_jpeg(output.getvalue())

    assert result is not None

    converted = Image.open(io.BytesIO(result)).convert("RGB")

    # Transparent pixels should become white.
    assert converted.getpixel((50, 50)) == (255, 255, 255)


# ---------------------------------------------------------------------
# download_one_image
# ---------------------------------------------------------------------

def test_download_one_image_saves_valid_image(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()
    client.get.return_value = make_response(
        make_image_bytes(),
    )

    result = downloader.download_one_image(
        client,
        "123456",
        ["https://example.com/image.jpg"],
    )

    output = tmp_path / "123456.jpg"

    assert result is True
    assert output.is_file()

    image = read_image(output)
    assert image.format == "JPEG"

    client.get.assert_called_once_with(
        "https://example.com/image.jpg",
    )


def test_download_one_image_skips_existing_file(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    output = tmp_path / "123456.jpg"
    output.write_bytes(b"existing image")

    client = Mock()

    result = downloader.download_one_image(
        client,
        "123456",
        ["https://example.com/image.jpg"],
    )

    assert result is True
    client.get.assert_not_called()


def test_download_one_image_returns_false_without_candidates(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()

    result = downloader.download_one_image(
        client,
        "123456",
        [],
    )

    assert result is False
    client.get.assert_not_called()


def test_download_one_image_tries_next_url_after_http_error(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()

    client.get.side_effect = [
        make_response(status_code=404),
        make_response(make_image_bytes()),
    ]

    result = downloader.download_one_image(
        client,
        "123456",
        [
            "https://example.com/broken.jpg",
            "https://example.com/valid.jpg",
        ],
    )

    assert result is True
    assert (tmp_path / "123456.jpg").is_file()
    assert client.get.call_count == 2


def test_download_one_image_tries_next_url_after_invalid_image(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()

    client.get.side_effect = [
        make_response(b"x" * downloader.MIN_IMAGE_BYTES),
        make_response(make_image_bytes()),
    ]

    result = downloader.download_one_image(
        client,
        "123456",
        [
            "https://example.com/invalid.jpg",
            "https://example.com/valid.jpg",
        ],
    )

    assert result is True
    assert (tmp_path / "123456.jpg").is_file()
    assert client.get.call_count == 2


def test_download_one_image_skips_invalid_url(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()
    client.get.return_value = make_response(
        make_image_bytes(),
    )

    result = downloader.download_one_image(
        client,
        "123456",
        [
            "ftp://example.com/image.jpg",
            "https://example.com/image.jpg",
        ],
    )

    assert result is True

    client.get.assert_called_once_with(
        "https://example.com/image.jpg",
    )


def test_download_one_image_returns_false_when_all_urls_fail(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()
    client.get.return_value = make_response(
        status_code=404,
    )

    result = downloader.download_one_image(
        client,
        "123456",
        [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
        ],
    )

    assert result is False
    assert not (tmp_path / "123456.jpg").exists()


def test_download_one_image_handles_connection_errors(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path,
    )

    client = Mock()
    client.get.side_effect = httpx.ConnectError(
        "connection failed",
    )

    result = downloader.download_one_image(
        client,
        "123456",
        ["https://example.com/image.jpg"],
    )

    assert result is False


# ---------------------------------------------------------------------
# load_database_item_codes
# ---------------------------------------------------------------------

def test_load_database_item_codes(monkeypatch):
    from contextlib import contextmanager

    cursor_context = MagicMock()
    cursor = cursor_context.__enter__.return_value

    cursor.fetchall.return_value = [
        ("123",),
        ("456",),
        (None,),
        (" 789 ",),
    ]

    @contextmanager
    def fake_connection():
        class Connection:
            def cursor(self):
                return cursor_context

        yield Connection()

    monkeypatch.setattr(
        "db.get_connection",
        fake_connection,
    )

    result = downloader.load_database_item_codes()

    assert result == {
        "123",
        "456",
        "789",
    }

    cursor.execute.assert_called_once()

    query = cursor.execute.call_args.args[0]

    assert "FROM products AS p" in query
    assert "INNER JOIN product_enrichment AS pe" in query
    assert "p.item_code IS NOT NULL" in query


# ---------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------

def test_parse_args_accepts_multiple_item_codes(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "download_product_images",
            "--item-code",
            "111",
            "--item-code",
            "222",
        ],
    )

    args = downloader.parse_args()

    assert args.item_codes == ["111", "222"]
    assert args.all is False


def test_parse_args_accepts_all(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "download_product_images",
            "--all",
        ],
    )

    args = downloader.parse_args()

    assert args.all is True
    assert args.item_codes is None


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def test_main_rejects_all_and_item_codes_together(
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=True,
            item_codes=["123"],
        ),
    )

    assert downloader.main() == 2


def test_main_requires_item_code_or_all(
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=False,
            item_codes=None,
        ),
    )

    assert downloader.main() == 2


def test_main_ignores_unknown_item_codes(
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=False,
            item_codes=["999"],
        ),
    )

    monkeypatch.setattr(
        downloader,
        "load_database_item_codes",
        lambda: {"111", "222"},
    )

    assert downloader.main() == 0


def test_main_returns_without_lookup_when_all_cached(
    tmp_path,
    monkeypatch,
):
    image_dir = tmp_path / "images"
    image_dir.mkdir()

    (image_dir / "111.jpg").write_bytes(b"cached")

    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        image_dir,
    )

    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=False,
            item_codes=["111"],
        ),
    )

    monkeypatch.setattr(
        downloader,
        "load_database_item_codes",
        lambda: {"111"},
    )

    collect = Mock()

    monkeypatch.setattr(
        downloader,
        "collect_image_candidates",
        collect,
    )

    assert downloader.main() == 0
    collect.assert_not_called()


def test_main_downloads_requested_products(
    tmp_path,
    monkeypatch,
):
    image_dir = tmp_path / "images"

    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        image_dir,
    )

    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=False,
            item_codes=["111", "222"],
        ),
    )

    monkeypatch.setattr(
        downloader,
        "load_database_item_codes",
        lambda: {"111", "222", "333"},
    )

    monkeypatch.setattr(
        downloader,
        "collect_image_candidates",
        lambda codes: {
            "111": ["https://example.com/111.jpg"],
            "222": ["https://example.com/222.jpg"],
        },
    )

    calls = []

    def fake_download(client, code, urls):
        calls.append((code, urls))
        return True

    monkeypatch.setattr(
        downloader,
        "download_one_image",
        fake_download,
    )

    assert downloader.main() == 0

    assert calls == [
        ("111", ["https://example.com/111.jpg"]),
        ("222", ["https://example.com/222.jpg"]),
    ]


def test_main_returns_one_when_download_fails(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path / "images",
    )

    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=False,
            item_codes=["111"],
        ),
    )

    monkeypatch.setattr(
        downloader,
        "load_database_item_codes",
        lambda: {"111"},
    )

    monkeypatch.setattr(
        downloader,
        "collect_image_candidates",
        lambda codes: {"111": []},
    )

    monkeypatch.setattr(
        downloader,
        "download_one_image",
        lambda *args: False,
    )

    assert downloader.main() == 1


def test_main_all_uses_database_codes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        downloader,
        "IMAGE_DIR",
        tmp_path / "images",
    )

    monkeypatch.setattr(
        downloader,
        "parse_args",
        lambda: Mock(
            all=True,
            item_codes=None,
        ),
    )

    monkeypatch.setattr(
        downloader,
        "load_database_item_codes",
        lambda: {"111", "222"},
    )

    collected = []

    monkeypatch.setattr(
        downloader,
        "collect_image_candidates",
        lambda codes: (
            collected.append(codes) or {
                "111": [],
                "222": [],
            }
        ),
    )

    monkeypatch.setattr(
        downloader,
        "download_one_image",
        lambda *args: False,
    )

    assert downloader.main() == 1
    assert collected == [{"111", "222"}]