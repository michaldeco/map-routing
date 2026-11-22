"""Minimal HTTP helpers (standard library only)."""

import urllib.request
from pathlib import Path


def get(url: str, user_agent: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download(url: str, target: Path, user_agent: str, timeout: float = 60.0) -> None:
    """Stream a URL to a file; the file appears only when complete."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp, partial.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    partial.replace(target)
