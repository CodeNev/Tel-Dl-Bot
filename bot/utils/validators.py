"""URL validation and security helpers.

These guard against:
 - command injection via crafted URLs/filenames passed to subprocesses
 - path traversal when writing downloaded files to disk
 - requests to domains the operator has explicitly blocked
 - obviously invalid or non-http(s) URLs
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Matches http(s) URLs only. Anything else (file://, javascript:, data:, etc.)
# is rejected outright.
_URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)

# Characters that have no business appearing in a URL we hand to a subprocess.
_DANGEROUS_CHARS = set(";&|`$()<>\n\r")


def extract_urls(text: str) -> list[str]:
    """Pull every http(s) URL out of a block of free text."""
    if not text:
        return []
    raw = re.findall(r"https?://[^\s]+", text)
    return [u.rstrip(").,!?\"'") for u in raw]


def is_valid_url(url: str) -> bool:
    if not url or len(url) > 2048:
        return False
    if not _URL_RE.match(url):
        return False
    if any(ch in _DANGEROUS_CHARS for ch in url):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    # Strip credentials and port if present.
    netloc = netloc.split("@")[-1].split(":")[0]
    return netloc


def is_domain_allowed(url: str, allowed: list[str], blocked: list[str]) -> bool:
    domain = domain_of(url)
    if not domain:
        return False

    def matches(patterns: list[str]) -> bool:
        return any(domain == p or domain.endswith("." + p) for p in patterns)

    if blocked and matches(blocked):
        return False
    if allowed and not matches(allowed):
        return False
    return True


_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._ \-]")


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Produce a filesystem-safe filename, preventing path traversal and
    stripping anything that isn't a plain ASCII-ish character."""
    name = name.strip().replace("/", "_").replace("\\", "_")
    name = name.replace("..", "_")
    name = _FILENAME_UNSAFE_RE.sub("_", name)
    name = re.sub(r"_+", "_", name).strip("._ ")
    if not name:
        name = "download"
    return name[:max_length]


def safe_join(base_dir, filename: str):
    """Join a filename onto a base directory, refusing any traversal attempt."""
    from pathlib import Path

    base = Path(base_dir).resolve()
    candidate = (base / sanitize_filename(filename)).resolve()
    if base not in candidate.parents and candidate != base:
        raise ValueError("Path traversal attempt detected")
    return candidate
