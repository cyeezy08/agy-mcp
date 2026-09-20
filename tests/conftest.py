"""Shared fixtures: isolated AGENTS_DIR + in-memory FastMCP client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastmcp import Client

from agy_mcp.server import mcp


@pytest.fixture()
async def agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AGENTS_DIR at a fresh temp dir for every test."""
    root = tmp_path / "agents"
    root.mkdir()
    monkeypatch.setenv("AGENTS_DIR", str(root))
    return root


@pytest.fixture()
async def client(agents_dir: Path) -> AsyncIterator[Client]:
    async with Client(mcp) as c:
        yield c


def make_skill(agents_dir: Path, name: str, content: str = "# skill") -> Path:
    d = agents_dir / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d
