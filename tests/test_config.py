"""Config tools: get / set / providers, plus type coercion behavior."""

from __future__ import annotations

import json
from pathlib import Path


async def test_get_config_missing_file(client, agents_dir: Path) -> None:
    r = await client.call_tool("agy_get_config", {})
    assert r.data == {"config": {}, "path": str(agents_dir / "config.json")}


async def test_set_then_get_roundtrip(client, agents_dir: Path) -> None:
    await client.call_tool("agy_set_config", {"key": "model", "value": "gemini-3-pro"})
    r = await client.call_tool("agy_get_config", {})
    assert r.data["config"] == {"model": "gemini-3-pro"}
    # file actually written to AGENTS_DIR
    assert json.loads((agents_dir / "config.json").read_text(encoding="utf-8")) == {
        "model": "gemini-3-pro"
    }


async def test_set_coerces_numeric_strings(client) -> None:
    r = await client.call_tool("agy_set_config", {"key": "retries", "value": "5"})
    assert r.data["value"] == 5  # int coercion
    r = await client.call_tool("agy_set_config", {"key": "threshold", "value": "0.75"})
    assert r.data["value"] == 0.75  # float coercion
    r = await client.call_tool("agy_set_config", {"key": "model", "value": "gpt"})
    assert r.data["value"] == "gpt"  # string passthrough


async def test_set_preserves_existing_keys(client) -> None:
    await client.call_tool("agy_set_config", {"key": "a", "value": "1"})
    await client.call_tool("agy_set_config", {"key": "b", "value": "x"})
    r = await client.call_tool("agy_get_config", {})
    assert r.data["config"] == {"a": 1, "b": "x"}


async def test_list_providers_empty(client) -> None:
    r = await client.call_tool("agy_list_providers", {})
    assert r.data == {"providers": [], "count": 0}


async def test_list_providers_dict_shape(client, agents_dir: Path) -> None:
    cfg = agents_dir / "config.json"
    cfg.write_text(json.dumps({"providers": {"google": {}, "openai": {}}}), encoding="utf-8")
    r = await client.call_tool("agy_list_providers", {})
    assert r.data["count"] == 2
    assert {p["name"] for p in r.data["providers"]} == {"google", "openai"}


async def test_list_providers_nested_llm_shape(client, agents_dir: Path) -> None:
    cfg = agents_dir / "config.json"
    cfg.write_text(json.dumps({"llm": {"providers": {"anthropic": {}}}}), encoding="utf-8")
    r = await client.call_tool("agy_list_providers", {})
    assert [p["name"] for p in r.data["providers"]] == ["anthropic"]


async def test_get_config_corrupt_file_returns_error(client, agents_dir: Path) -> None:
    (agents_dir / "config.json").write_text("{not json", encoding="utf-8")
    r = await client.call_tool("agy_get_config", {})
    assert "error" in r.data
