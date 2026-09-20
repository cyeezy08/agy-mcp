"""Security regressions for the 0.2.0 traversal fixes.

0.1.0 allowed skill names containing '..' and path separators, which meant:
  - agy_read_skill("../victim")    -> read SKILL.md files anywhere on disk
  - agy_install_skill("../escaped") -> write SKILL.md outside the skills dir
  - agy_delete_skill("..")         -> shutil.rmtree() of an arbitrary directory
All three must now be rejected. Do not weaken these tests.
"""

from __future__ import annotations

from pathlib import Path

from conftest import make_skill

TRAVERSAL_NAMES = [
    "..",
    "../victim",
    "..\\victim",
    "skills/../../escape",
    "a/../b",
    ".",
    "./dot",
    "sub/dir",
    "skill name with spaces",
    "nul\x00byte",
    "-leading-dash-not-start-alnum",
]


async def test_read_skill_rejects_traversal(client, agents_dir: Path) -> None:
    victim = agents_dir / "victim"
    victim.mkdir()
    (victim / "SKILL.md").write_text("LEAKED CONTENT", encoding="utf-8")
    for name in ["..", "../victim", "sub/dir", "."]:
        r = await client.call_tool("agy_read_skill", {"skill_name": name})
        assert "error" in r.data, f"traversal name {name!r} was not rejected"
        assert "LEAKED" not in str(r.data)


async def test_read_skill_cannot_leak_arbitrary_files(client, agents_dir: Path) -> None:
    # 0.1.0 joined SKILL.md after the traversal, so plain-file reads failed —
    # verify that stays true and no error message leaks file content.
    secret = agents_dir / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    r = await client.call_tool("agy_read_skill", {"skill_name": "../secret.txt"})
    assert "TOP SECRET" not in str(r.data)


async def test_install_skill_rejects_traversal(client, agents_dir: Path) -> None:
    for name in ["..", "../escaped", "a/b", "."]:
        r = await client.call_tool("agy_install_skill", {"skill_name": name, "content": "planted"})
        assert r.data.get("success") is False, f"traversal name {name!r} was not rejected"
    # nothing may exist outside the skills dir (skills/ itself may not exist yet)
    assert {p.name for p in agents_dir.iterdir()} <= {"skills"}
    assert not (agents_dir / "escaped").exists()


async def test_delete_skill_rejects_traversal(client, agents_dir: Path) -> None:
    make_skill(agents_dir, "real-skill")
    sentinel = agents_dir / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    for name in ["..", "../", "skills/.."]:
        r = await client.call_tool("agy_delete_skill", {"skill_name": name})
        assert r.data.get("success") is False, f"traversal name {name!r} was not rejected"
    # the kill-shot from the 0.1.0 advisory: rmtree of the parent dir
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert (agents_dir / "skills" / "real-skill").is_dir()


async def test_valid_names_still_accepted(client) -> None:
    for name in ["python-expert", "fleet_2", "my.skill", "A1"]:
        r = await client.call_tool("agy_install_skill", {"skill_name": name, "content": "# x"})
        assert r.data == {"success": True, "name": name}


async def test_symlink_escape_is_contained(client, agents_dir: Path) -> None:
    """A symlink inside skills/ pointing outside must not become a write target."""
    (agents_dir / "skills").mkdir(parents=True)
    outside = agents_dir / "outside"
    outside.mkdir()
    link = agents_dir / "skills" / "evil-link"
    link.symlink_to(outside, target_is_directory=True)
    r = await client.call_tool("agy_read_skill", {"skill_name": "evil-link"})
    # read of a linked dir without SKILL.md is a clean miss, not a crash
    assert "error" in r.data or "content" in r.data
    r = await client.call_tool(
        "agy_install_skill", {"skill_name": "evil-link", "content": "# planted"}
    )
    # rejected by the resolve-containment check before any filesystem write
    assert r.data.get("success") is False
    assert not (outside / "SKILL.md").exists()
