"""
Compatibility shim for Python 3.14+.

The standard library module `imghdr` was removed in Python 3.14, but some
third-party libraries (including certain Streamlit builds) still import it.

This file provides a minimal subset of the old `imghdr` API so imports succeed.
"""

from __future__ import annotations

from typing import Optional


def what(file=None, h: bytes | None = None) -> Optional[str]:
    """
    Determine the image type.

    Args:
        file: A filename/path, file-like object, or None.
        h: Optional initial bytes.

    Returns:
        A lowercase image type string like "jpeg", "png", "gif", "webp", "bmp", "tiff",
        or None if unknown.
    """
    if h is None:
        if file is None:
            return None
        if isinstance(file, (str, bytes, bytearray)):
            with open(file, "rb") as f:
                h = f.read(64)
        else:
            # file-like
            pos = None
            try:
                pos = file.tell()
            except Exception:
                pos = None
            h = file.read(64)
            try:
                if pos is not None:
                    file.seek(pos)
            except Exception:
                pass

    if not h:
        return None

    # JPEG
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    # PNG
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # GIF
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    # WebP: "RIFF" .... "WEBP"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    # BMP
    if h[:2] == b"BM":
        return "bmp"
    # TIFF
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"

    return None

