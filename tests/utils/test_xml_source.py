import gzip
import zipfile
from pathlib import Path

import pytest

from utils.xml_source import iter_xml_from_path


def test_plain_xml(tmp_path):
    path = tmp_path / "test.xml"
    data = b"<root>hello</root>"
    path.write_bytes(data)

    assert list(iter_xml_from_path(path)) == [data]


def test_gzip(tmp_path):
    path = tmp_path / "test.gz"
    data = b"<root>hello</root>"

    with gzip.open(path, "wb") as f:
        f.write(data)

    assert list(iter_xml_from_path(path)) == [data]


def test_xml_gzip(tmp_path):
    path = tmp_path / "test.xml.gz"
    data = b"<root>hello</root>"

    with gzip.open(path, "wb") as f:
        f.write(data)

    assert list(iter_xml_from_path(path)) == [data]


def test_zip_single_xml(tmp_path):
    path = tmp_path / "test.zip"
    data = b"<root>hello</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.xml", data)

    assert list(iter_xml_from_path(path)) == [data]


def test_zip_multiple_xml(tmp_path):
    path = tmp_path / "test.zip"

    data1 = b"<root>one</root>"
    data2 = b"<root>two</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("one.xml", data1)
        zf.writestr("two.xml", data2)

    assert list(iter_xml_from_path(path)) == [data1, data2]


def test_zip_xml_gz(tmp_path):
    path = tmp_path / "test.zip"
    data = b"<root>hello</root>"
    compressed = gzip.compress(data)

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.xml.gz", compressed)

    assert list(iter_xml_from_path(path)) == [data]


def test_zip_ignores_non_xml_members(tmp_path):
    path = tmp_path / "test.zip"
    data = b"<root>hello</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", b"not xml")
        zf.writestr("test.xml", data)

    assert list(iter_xml_from_path(path)) == [data]


def test_zip_ignores_directories(tmp_path):
    path = tmp_path / "test.zip"
    data = b"<root>hello</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("folder/", b"")
        zf.writestr("folder/test.xml", data)

    assert list(iter_xml_from_path(path)) == [data]


def test_zip_without_xml_raises(tmp_path):
    path = tmp_path / "test.zip"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.txt", b"not xml")

    with pytest.raises(ValueError, match="ZIP contains no XML files"):
        list(iter_xml_from_path(path))


def test_gz_extension_but_actually_zip(tmp_path):
    path = tmp_path / "test.gz"
    data = b"<root>hello</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.xml", data)

    assert list(iter_xml_from_path(path)) == [data]


def test_extensionless_gzip(tmp_path):
    path = tmp_path / "test"
    data = b"<root>hello</root>"

    with gzip.open(path, "wb") as f:
        f.write(data)

    assert list(iter_xml_from_path(path)) == [data]


def test_extensionless_zip(tmp_path):
    path = tmp_path / "test"
    data = b"<root>hello</root>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("test.xml", data)

    assert list(iter_xml_from_path(path)) == [data]


def test_extensionless_plain_xml(tmp_path):
    path = tmp_path / "test"
    data = b"<root>hello</root>"
    path.write_bytes(data)

    assert list(iter_xml_from_path(path)) == [data]