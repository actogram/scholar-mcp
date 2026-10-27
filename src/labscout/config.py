"""Settings from environment variables, so the same code runs on a laptop, in CI and on a server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "https://github.com/actogram/scholar-mcp"


@dataclass(frozen=True)
class Settings:
    email: str = ""  # contact address for NCBI and the User-Agent, as their usage policies ask
    ncbi_api_key: str = ""  # optional: 10 requests per second at NCBI instead of 3
    cache_dir: Path | None = None  # None switches the disk cache off
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        """LABSCOUT_EMAIL, NCBI_API_KEY and LABSCOUT_CACHE_DIR (an empty value switches the cache off)."""
        cache = os.environ.get("LABSCOUT_CACHE_DIR")
        if cache is None:
            base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
            cache = str(base / "labscout")
        return cls(
            email=os.environ.get("LABSCOUT_EMAIL", "").strip(),
            ncbi_api_key=os.environ.get("NCBI_API_KEY", "").strip(),
            cache_dir=Path(cache) if cache else None,
        )

    @property
    def user_agent(self) -> str:
        contact = f"; mailto:{self.email}" if self.email else ""
        return f"labscout/{__version__} (+{REPO}{contact})"
