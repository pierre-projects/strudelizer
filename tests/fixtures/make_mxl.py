"""Build the compressed MusicXML fixture (.mxl) from score.musicxml.

    python tests/fixtures/make_mxl.py

An .mxl file is a zip holding the score and META-INF/container.xml that
points at it. Timestamps are fixed so the bytes are reproducible.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

HERE = Path(__file__).parent / "musicxml"
SOURCE = HERE / "score.musicxml"
TARGET = HERE / "score_compressed.mxl"
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container>
  <rootfiles>
    <rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>
  </rootfiles>
</container>
"""
STAMP = (2026, 1, 1, 0, 0, 0)


def build() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, method in [
            ("mimetype", b"application/vnd.recordare.musicxml", zipfile.ZIP_STORED),
            ("META-INF/container.xml", CONTAINER.encode("utf-8"), zipfile.ZIP_DEFLATED),
            ("score.musicxml", SOURCE.read_bytes(), zipfile.ZIP_DEFLATED),
        ]:
            info = zipfile.ZipInfo(name, date_time=STAMP)
            info.compress_type = method
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def main() -> None:
    TARGET.write_bytes(build())
    print(f"wrote musicxml/{TARGET.name}")


if __name__ == "__main__":
    main()
