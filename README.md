# agy-mcp

MCP server for [Antigravity IDE](https://antigravity.google/) — skill management, config bridge, and agent orchestration.

Wraps Antigravity's local `~/.agents/` directory (skills, `.skill-lock.json`, `config.json`) as MCP tools, so an assistant can list, read, install, and search Antigravity skills, and read or write Antigravity configuration, without shelling out manually.

## Status (0.2.0)

Single-file server (`src/agy_mcp/server.py`) exposing 11 tools plus `agy_help`, covered by a 34-test pytest suite (skill CRUD, config, GitHub install with stubbed clone, security regressions) running in CI on Linux + Windows, Python 3.11 and 3.12.

**Security note:** 0.1.0 joined caller-supplied skill names directly into filesystem paths, so `agy_delete_skill("..")` could delete arbitrary directories and `agy_read_skill("../victim")` could read files outside the skills directory. 0.2.0 validates every skill name against a strict charset and containment-checks the resolved path before any read, write, or delete. Because this server is driven by an LLM, treat these regressions as load-bearing — see `tests/test_security.py` before weakening name validation.

## Tools

| Tool | Description |
|------|-------------|
| `agy_list_skills` | List installed skills from `~/.agents/skills/`, merged with lock metadata |
| `agy_read_skill` | Read a skill's full `SKILL.md` |
| `agy_search_skills` | Search skill names and content |
| `agy_install_skill` | Write or update a skill's `SKILL.md`, register it in the lock file |
| `agy_delete_skill` | Remove an installed skill |
| `agy_install_skill_from_github` | Clone a GitHub repo, pull a `SKILL.md` out of it, install as a skill |
| `agy_get_config` / `agy_set_config` | Read/write Antigravity's `config.json` |
| `agy_list_providers` | List configured LLM providers from config |
| `agy_skill_lock_status` | Read `.skill-lock.json` (sources, versions) |
| `agy_version` | Report the installed Antigravity CLI version |
| `agy_help` | List all tools |

## Quick start

```powershell
cd D:\Dev\repos\agy-mcp
uv sync
uv run agy-mcp
```

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agy-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\Dev\\repos\\agy-mcp", "agy-mcp"]
    }
  }
}
```

By default it reads and writes `~/.agents/` — override with the `AGENTS_DIR` environment variable (resolved per call, so it can also be set just for tests).

## Development

```bash
uv sync --group dev        # pytest, pytest-asyncio, ruff, pre-commit
uv run pytest -q           # 34 tests, < 1s, no network
uv run ruff check src tests
uv run ruff format src tests
just bootstrap             # Windows: also installs the pre-commit hook
```

CI (`.github/workflows/ci.yml`) runs lint + tests on `ubuntu-latest` and `windows-latest` across Python 3.11/3.12; `scripts/ci.ps1` mirrors the same gates locally on Windows.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- FastMCP 3.4+
