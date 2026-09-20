"""Skill CRUD round-trips: list / read / search / install / delete."""

from __future__ import annotations

from pathlib import Path

from conftest import make_skill


async def test_empty_skills_dir(client) -> None:
    r = await client.call_tool("agy_list_skills", {})
    assert r.data == {"skills": [], "count": 0}


async def test_missing_skills_dir(client) -> None:
    r = await client.call_tool("agy_list_skills", {})
    assert r.data["count"] == 0  # never created — still safe


async def test_list_merges_lock_metadata(client, agents_dir: Path) -> None:
    make_skill(agents_dir, "alpha")
    r = await client.call_tool("agy_list_skills", {})
    assert r.data["count"] == 1
    assert r.data["skills"][0]["name"] == "alpha"
    assert r.data["skills"][0]["source_type"] == "local"


async def test_read_skill_roundtrip(client, agents_dir: Path) -> None:
    make_skill(agents_dir, "alpha", "# Alpha\n\nbody text")
    r = await client.call_tool("agy_read_skill", {"skill_name": "alpha"})
    assert r.data["name"] == "alpha"
    assert "Alpha" in r.data["content"]
    assert r.data["meta"] == {}


async def test_read_missing_skill(client) -> None:
    r = await client.call_tool("agy_read_skill", {"skill_name": "ghost"})
    assert r.data["error"] == "Skill 'ghost' not found"


async def test_search_by_name_and_content(client, agents_dir: Path) -> None:
    make_skill(agents_dir, "python-expert", "teaches docker too")
    make_skill(agents_dir, "other", "nothing relevant")
    by_name = await client.call_tool("agy_search_skills", {"query": "python"})
    assert by_name.data["results"] == [{"name": "python-expert", "match": "name"}]
    by_content = await client.call_tool("agy_search_skills", {"query": "docker"})
    assert by_content.data["results"] == [{"name": "python-expert", "match": "content"}]
    miss = await client.call_tool("agy_search_skills", {"query": "kubernetes"})
    assert miss.data["count"] == 0


async def test_install_then_delete_roundtrip(client, agents_dir: Path) -> None:
    r = await client.call_tool(
        "agy_install_skill", {"skill_name": "fresh", "content": "# fresh skill"}
    )
    assert r.data == {"success": True, "name": "fresh"}
    assert (agents_dir / "skills" / "fresh" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# fresh skill"

    # lock registration happened
    lock_status = await client.call_tool("agy_skill_lock_status", {})
    assert lock_status.data["count"] == 1
    assert lock_status.data["skills"][0]["name"] == "fresh"

    # overwrite (update path)
    await client.call_tool("agy_install_skill", {"skill_name": "fresh", "content": "# v2"})
    assert (agents_dir / "skills" / "fresh" / "SKILL.md").read_text(encoding="utf-8") == "# v2"
    assert (await client.call_tool("agy_skill_lock_status", {})).data["count"] == 1

    # delete
    r = await client.call_tool("agy_delete_skill", {"skill_name": "fresh"})
    assert r.data == {"success": True, "name": "fresh"}
    assert not (agents_dir / "skills" / "fresh").exists()
    assert (await client.call_tool("agy_skill_lock_status", {})).data["count"] == 0


async def test_delete_missing_skill(client) -> None:
    r = await client.call_tool("agy_delete_skill", {"skill_name": "ghost"})
    assert r.data == {"success": False, "error": "Skill 'ghost' not found"}


async def test_lock_status_on_missing_lock(client) -> None:
    r = await client.call_tool("agy_skill_lock_status", {})
    assert r.data == {"version": 0, "skills": [], "count": 0}
