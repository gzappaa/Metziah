"""
utils/xml_source.py

XML container reader for feed files.

Provides iter_xml_from_path(), which yields complete XML documents as
bytes from feed files that may be:

    - plain XML
    - GZIP-compressed
    - XML.GZ
    - ZIP archives
    - extensionless or incorrectly named files

Filename extensions are treated as hints rather than authoritative file
types. When the extension is missing or misleading, the reader falls
back through:

    GZIP -> ZIP -> plain XML

ZIP archives may contain multiple XML documents. Each XML-like member is
decompressed when necessary and yielded separately.

This utility centralizes feed-container handling so loaders do not need
to assume that one file contains exactly one XML document or that its
filename extension accurately describes the underlying format.
"""


import gzip
import zipfile
from pathlib import Path


def iter_xml_from_path(path: Path):
    """
    Yield complete XML documents as bytes from:

        .xml
        .gz
        .xml.gz
        .zip
        extensionless / unknown files

    Filename extensions are treated as hints, not guaranteed truth.

    Fallbacks:
        GZIP -> ZIP
        unknown -> GZIP -> ZIP -> plain XML

    For ZIP files, every XML-like member is yielded as a separate
    complete XML document.
    """

    suffixes = [suffix.lower() for suffix in path.suffixes]

    # ------------------------------------------------------------
    # ZIP
    # ------------------------------------------------------------

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
                raise ValueError("ZIP contains no XML files")

            for member in members:
                with zf.open(member) as raw:
                    data = raw.read()

                if member.lower().endswith(".gz"):
                    data = gzip.decompress(data)

                yield data

    # ------------------------------------------------------------
    # ZIP by extension
    # ------------------------------------------------------------

    if ".zip" in suffixes:
        yield from iter_zip()
        return

    # ------------------------------------------------------------
    # GZIP by extension
    # ------------------------------------------------------------

    if ".gz" in suffixes:
        try:
            with gzip.open(path, "rb") as f:
                yield f.read()

            return

        except (gzip.BadGzipFile, OSError, EOFError):
            # Some files are incorrectly named .gz but are actually
            # ZIP archives.
            yield from iter_zip()
            return

    # ------------------------------------------------------------
    # XML by extension
    # ------------------------------------------------------------

    if ".xml" in suffixes:
        yield path.read_bytes()
        return

    # ------------------------------------------------------------
    # Unknown / extensionless
    #
    # Try:
    #     GZIP -> ZIP -> plain XML
    # ------------------------------------------------------------

    try:
        with gzip.open(path, "rb") as f:
            yield f.read()

        return

    except (gzip.BadGzipFile, OSError, EOFError):
        pass

    try:
        yield from iter_zip()
        return

    except zipfile.BadZipFile:
        pass

    # Final fallback: plain XML
    yield path.read_bytes()