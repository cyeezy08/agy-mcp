"""Server metadata: tool registration, help output, version consistency."""

from __future__ import annotations

import agy_mcp.server as server

EXPECTED_TOOLS = {
    "agy_list_skills",
    "agy_read_skill",
    "agy_search_skills",
    "agy_install_skill",
    "agy_delete_skill",
    "agy_get_config",
    "agy_set_config",
    "agy_list_providers",
    "agy_skill_lock_status",
    "agy_install_skill_from_github",
    "agy_version",
    "agy_help",
}


async def test_all_tools_registered(client) -> None:
    tools = {t.name for t in await client.list_tools()}
    assert tools == EXPECTED_TOOLS


async def test_help_lists_all_tools(client) -> None:
    r = await client.call_tool("agy_help", {})
    listed = {t["name"] for t in r.data["tools"]}
    assert listed == EXPECTED_TOOLS - {"agy_help"}
    assert r.data["version"] == server.__version__


async def test_version_matches_pyproject() -> None:
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == server.__version__


async def test_tools_have_annotations(client) -> None:
    """Read-only tools must carry the readonly annotation (0.1.0 contract)."""
    tools = {t.name: t for t in await client.list_tools()}
    ro = {
        "agy_list_skills",
        "agy_read_skill",
        "agy_search_skills",
        "agy_get_config",
        "agy_list_providers",
        "agy_skill_lock_status",
        "agy_version",
        "agy_help",
    }
    for name in ro:
        annotations = tools[name].annotations
        # fastmcp exposes the hint as `readonly`; the MCP spec calls it readOnlyHint
        hinted = getattr(annotations, "readonly", None) or getattr(
            annotations, "readOnlyHint", None
        )
        assert annotations is not None and hinted is True, name


async def test_agy_version_tool_reports_gracefully(client) -> None:
    """No antigravity CLI in test env -> structured 'unknown', never a raise."""
    r = await client.call_tool("agy_version", {})
    assert r.data["version"] == "unknown"
    assert "not found" in r.data["path"]
