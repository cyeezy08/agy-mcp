"""agy_install_skill_from_github with a stubbed git clone (no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import agy_mcp.server as server


class FakeClone:
    """Intercepts subprocess.run inside the tool and fabricates a cloned repo."""

    def __init__(self, skill_path: str = "SKILL.md", content: str = "# from github") -> None:
        self.skill_path = skill_path
        self.content = content
        self.calls: list[list[str]] = []

    def __enter__(self):
        self._orig = server.subprocess.run

        def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
            self.calls.append(cmd)
            dest = Path(cmd[-1])  # clone target dir
            if cmd[1] == "clone" and any("github.com" in str(c) for c in cmd):
                (dest / self.skill_path).parent.mkdir(parents=True, exist_ok=True)
                (dest / self.skill_path).write_text(self.content, encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            raise subprocess.TimeoutExpired(cmd, timeout=60)

        server.subprocess.run = fake_run
        return self

    def __exit__(self, *exc) -> None:
        server.subprocess.run = self._orig


async def test_install_from_github_success(client, agents_dir: Path) -> None:
    with FakeClone() as fake:
        r = await client.call_tool("agy_install_skill_from_github", {"repo": "owner/some-skill"})
    assert r.data == {"success": True, "repo": "owner/some-skill", "skill_name": "some-skill"}
    assert (agents_dir / "skills" / "some-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# from github"
    # clone was shallow and hit the right URL
    assert fake.calls and "--depth" in fake.calls[0]
    # temp clone dir cleaned up
    import tempfile

    assert not any(Path(tempfile.gettempdir()).glob("tmp*/repo"))


async def test_install_from_github_nested_skill_path(client, agents_dir: Path) -> None:
    with FakeClone(skill_path="skills/fleet-expert/SKILL.md"):
        r = await client.call_tool(
            "agy_install_skill_from_github",
            {"repo": "owner/docs", "skill_path": "skills/fleet-expert"},
        )
    assert r.data["skill_name"] == "fleet-expert"
    assert (agents_dir / "skills" / "fleet-expert" / "SKILL.md").is_file()
    lock = await client.call_tool("agy_skill_lock_status", {})
    entry = next(s for s in lock.data["skills"] if s["name"] == "fleet-expert")
    assert entry["sourceType"] == "github"


async def test_install_from_github_no_skill_md(client, agents_dir: Path) -> None:
    with FakeClone(skill_path="README.md"):  # clone has no SKILL.md anywhere
        r = await client.call_tool("agy_install_skill_from_github", {"repo": "owner/notaskill"})
    assert r.data["success"] is False
    assert "No SKILL.md" in r.data["error"]


async def test_install_from_github_bad_repo_shape(client) -> None:
    for bad in ["", "justname", "a/b/c", "https://gitlab.com/owner/repo"]:
        r = await client.call_tool("agy_install_skill_from_github", {"repo": bad})
        assert r.data["success"] is False, f"{bad!r} should be rejected"
        assert "clone" not in r.data  # rejected before any git call


async def test_install_from_github_url_forms_normalized(client, agents_dir: Path) -> None:
    for form in [
        "https://github.com/owner/repo-x",
        "owner/repo-x.git",
        "https://github.com/owner/repo-x.git",
    ]:
        with FakeClone():
            r = await client.call_tool("agy_install_skill_from_github", {"repo": form})
        assert r.data["success"] is True, f"URL form {form!r} failed"
        assert r.data["repo"] == "owner/repo-x"


async def test_install_from_github_clone_failure(
    client, agents_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git failing (network down, 404 repo) must yield a clean error dict."""

    def failing_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        raise subprocess.CalledProcessError(returncode=128, cmd=cmd)

    monkeypatch.setattr(server.subprocess, "run", failing_run)
    r = await client.call_tool("agy_install_skill_from_github", {"repo": "owner/nope"})
    assert r.data["success"] is False
    assert "error" in r.data
    # no skill dir was created
    assert not (agents_dir / "skills" / "nope").exists()
