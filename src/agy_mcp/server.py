"""FastMCP server for Antigravity IDE - skills, config, sessions, providers.

Security model:
- Skill names are validated against a strict pattern and resolved paths are
  containment-checked, so no tool can read, write, or delete outside
  ``AGENTS_DIR`` (defaults to ``~/.agents``).
- All filesystem access runs in worker threads via ``asyncio.to_thread``;
  the event loop never blocks on disk I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

log = logging.getLogger(__name__)

__version__ = "0.2.0"

DEFAULT_AGENTS_DIR = Path(os.getenv("AGENTS_DIR", os.path.expanduser("~/.agents")))


def _agents_dir() -> Path:
    """Resolve the Antigravity data dir per call (env may change at runtime)."""
    return Path(os.getenv("AGENTS_DIR", str(DEFAULT_AGENTS_DIR)))


def _skills_dir() -> Path:
    return _agents_dir() / "skills"


def _lock_file() -> Path:
    return _agents_dir() / ".skill-lock.json"


def _config_file() -> Path:
    return _agents_dir() / "config.json"


mcp = FastMCP(
    "agy-mcp",
    instructions="MCP server for Antigravity IDE - manage skills, config, providers, and agent sessions.",
    version=__version__,
)

_READ_ONLY = {"readonly": True}
_MUTATING = {}

# One charset for skill directory names: letters, digits, dot, underscore,
# dash. Must start alnum, 1-128 chars. Rejects path separators, "..", NUL,
# whitespace, and everything else that could escape the skills directory.
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_skill_name(skill_name: str) -> str | None:
    """Return an error message when ``skill_name`` is unsafe, else ``None``."""
    if not skill_name or not _SKILL_NAME_RE.fullmatch(skill_name):
        return (
            f"Invalid skill name {skill_name!r}: expected 1-128 chars of "
            "letters, digits, '.', '_' or '-', starting with a letter or digit "
            "(no path separators, no '..')"
        )
    skills_root = _skills_dir().resolve()
    resolved = (skills_root / skill_name).resolve()
    if resolved != skills_root and skills_root not in resolved.parents:
        return f"Invalid skill name {skill_name!r}: resolves outside the skills directory"
    return None


def _read_lock_sync() -> dict:
    lock_file = _lock_file()
    if not lock_file.is_file():
        return {"skills": {}, "version": 0}
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"skills": {}, "version": 0}


def _write_lock_sync(data: dict) -> bool:
    try:
        _lock_file().write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


# ── Skills: Read ──────────────────────────────────────────────────────────────


def _list_skills_sync() -> dict:
    skills_root = _skills_dir()
    if not skills_root.is_dir():
        return {"skills": [], "count": 0}
    lock = _read_lock_sync()
    skills = []
    for entry in sorted(skills_root.iterdir()):
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            meta = lock.get("skills", {}).get(entry.name, {})
            skills.append(
                {
                    "name": entry.name,
                    "source": meta.get("source", ""),
                    "source_type": meta.get("sourceType", "local"),
                }
            )
    return {"skills": skills, "count": len(skills)}


@mcp.tool(annotations=_READ_ONLY)
async def agy_list_skills(ctx: Any = None) -> dict:
    """List all installed Antigravity agent skills with source info.

    Scans ~/.agents/skills/ and merges metadata from .skill-lock.json.

    ## Return Format
    {"skills": [{"name": str, "source": str, "source_type": str}], "count": int}
    """
    return await asyncio.to_thread(_list_skills_sync)


def _read_skill_sync(skill_name: str) -> dict:
    invalid = _validate_skill_name(skill_name)
    if invalid:
        return {"error": invalid, "skills_dir": str(_skills_dir())}
    skill_file = _skills_dir() / skill_name / "SKILL.md"
    if not skill_file.is_file():
        return {"error": f"Skill '{skill_name}' not found", "skills_dir": str(_skills_dir())}
    lock = _read_lock_sync()
    return {
        "name": skill_name,
        "content": skill_file.read_text(encoding="utf-8"),
        "meta": lock.get("skills", {}).get(skill_name, {}),
    }


@mcp.tool(annotations=_READ_ONLY)
async def agy_read_skill(skill_name: str, ctx: Any = None) -> dict:
    """Read a skill's full SKILL.md content.

    ## Return Format
    {"name": str, "content": str, "meta": dict}

    ## Examples
    agy_read_skill("python-expert")
    """
    return await asyncio.to_thread(_read_skill_sync, skill_name)


def _search_skills_sync(query: str) -> dict:
    query_lower = query.lower()
    results = []
    skills_root = _skills_dir()
    if not skills_root.is_dir():
        return {"results": [], "count": 0}
    for entry in sorted(skills_root.iterdir()):
        skill_file = entry / "SKILL.md"
        if not (entry.is_dir() and skill_file.is_file()):
            continue
        if query_lower in entry.name.lower():
            results.append({"name": entry.name, "match": "name"})
            continue
        try:
            content = skill_file.read_text(encoding="utf-8").lower()
            if query_lower in content:
                results.append({"name": entry.name, "match": "content"})
        except OSError:
            pass
    return {"results": results, "count": len(results)}


@mcp.tool(annotations=_READ_ONLY)
async def agy_search_skills(query: str, ctx: Any = None) -> dict:
    """Search across all installed skill names and content.

    ## Return Format
    {"results": [{"name": str, "match": str}], "count": int}

    ## Examples
    agy_search_skills("python")
    agy_search_skills("docker")
    """
    return await asyncio.to_thread(_search_skills_sync, query)


# ── Skills: Write ─────────────────────────────────────────────────────────────


def _install_skill_sync(skill_name: str, content: str) -> dict:
    invalid = _validate_skill_name(skill_name)
    if invalid:
        return {"success": False, "error": invalid}
    path = _skills_dir() / skill_name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")
    # Register in lock file
    lock = _read_lock_sync()
    lock["skills"][skill_name] = {
        "source": "local",
        "sourceType": "local",
        "installedAt": str(__import__("datetime").datetime.now().isoformat()),
    }
    _write_lock_sync(lock)
    return {"success": True, "name": skill_name}


@mcp.tool(annotations=_MUTATING)
async def agy_install_skill(skill_name: str, content: str, ctx: Any = None) -> dict:
    """Create or update a skill by writing its SKILL.md.

    Also registers the skill in .skill-lock.json as a local skill.

    ## Return Format
    {"success": bool, "name": str}

    ## Examples
    agy_install_skill("my-skill", "# My Skill\\n\\nBe helpful and concise.")
    """
    return await asyncio.to_thread(_install_skill_sync, skill_name, content)


def _delete_skill_sync(skill_name: str) -> dict:
    import shutil

    invalid = _validate_skill_name(skill_name)
    if invalid:
        return {"success": False, "error": invalid}
    path = _skills_dir() / skill_name
    if not path.is_dir():
        return {"success": False, "error": f"Skill '{skill_name}' not found"}
    try:
        shutil.rmtree(path)
        lock = _read_lock_sync()
        lock["skills"].pop(skill_name, None)
        _write_lock_sync(lock)
        return {"success": True, "name": skill_name}
    except OSError as e:
        return {"success": False, "error": str(e)}


@mcp.tool(annotations=_MUTATING)
async def agy_delete_skill(skill_name: str, ctx: Any = None) -> dict:
    """Permanently remove an installed skill.

    ## Return Format
    {"success": bool, "name": str}

    ## Examples
    agy_delete_skill("old-skill")
    """
    return await asyncio.to_thread(_delete_skill_sync, skill_name)


# ── Config ────────────────────────────────────────────────────────────────────


def _get_config_sync() -> dict:
    config_file = _config_file()
    if not config_file.is_file():
        return {"config": {}, "path": str(config_file)}
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return {"config": data, "path": str(config_file)}
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to read config: {e}"}


@mcp.tool(annotations=_READ_ONLY)
async def agy_get_config(ctx: Any = None) -> dict:
    """Read the full Antigravity configuration.

    ## Return Format
    {"config": dict, "path": str}
    """
    return await asyncio.to_thread(_get_config_sync)


def _set_config_sync(key: str, value: str) -> dict:
    try:
        value_converted: Any = int(value)
    except (ValueError, TypeError):
        try:
            value_converted = float(value)
        except (ValueError, TypeError):
            value_converted = value
    config_file = _config_file()
    current = {}
    if config_file.is_file():
        try:
            current = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    current[key] = value_converted
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return {"success": True, "key": key, "value": value_converted}


@mcp.tool(annotations=_MUTATING)
async def agy_set_config(key: str, value: str, ctx: Any = None) -> dict:
    """Set a configuration value in Antigravity config.json.

    Creates the config file if it doesn't exist.

    ## Return Format
    {"success": bool, "key": str, "value": any}

    ## Examples
    agy_set_config("default_model", "claude-sonnet-4-6")
    """
    return await asyncio.to_thread(_set_config_sync, key, value)


# ── Provider info ─────────────────────────────────────────────────────────────


def _list_providers_sync() -> dict:
    config_file = _config_file()
    if not config_file.is_file():
        return {"providers": [], "count": 0}
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        providers = data.get("providers", data.get("llm", {}).get("providers", {}))
        if isinstance(providers, dict):
            return {"providers": [{"name": k} for k in providers], "count": len(providers)}
        return {"providers": [], "count": 0}
    except (json.JSONDecodeError, OSError):
        return {"providers": [], "count": 0}


@mcp.tool(annotations=_READ_ONLY)
async def agy_list_providers(ctx: Any = None) -> dict:
    """List configured LLM providers from Antigravity config.

    Reads the providers section from config.json.

    ## Return Format
    {"providers": [{"name": str}], "count": int}
    """
    return await asyncio.to_thread(_list_providers_sync)


# ── Skill Lock / Marketplace ──────────────────────────────────────────────────


@mcp.tool(annotations=_READ_ONLY)
async def agy_skill_lock_status(ctx: Any = None) -> dict:
    """Read the .skill-lock.json to see installed skill sources and versions.

    ## Return Format
    {"version": int, "skills": [{"name": str, "source": str, "source_type": str}], "count": int}
    """
    lock = await asyncio.to_thread(_read_lock_sync)
    skills = [{"name": k, **v} for k, v in lock.get("skills", {}).items()]
    return {"version": lock.get("version", 0), "skills": skills, "count": len(skills)}


def _install_from_github_sync(tmpdir: str, repo: str, skill_path: str) -> dict:
    """Post-clone half of GitHub install: extract, register, clean up."""
    import shutil

    repo_name = repo.split("/")[-1].replace(".git", "")
    skill_name = skill_path.split("/")[-1] if skill_path else repo_name
    invalid = _validate_skill_name(skill_name)
    if invalid:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"success": False, "error": invalid}
    dest = _skills_dir() / skill_name
    try:
        src = Path(tmpdir) / "repo" / skill_path if skill_path else Path(tmpdir) / "repo"
        src_skill = src / "SKILL.md" if src.is_dir() else src
        if src_skill.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_skill), str(dest / "SKILL.md"))
            lock = _read_lock_sync()
            lock["skills"][skill_name] = {
                "source": repo,
                "sourceType": "github",
                "sourceUrl": f"https://github.com/{repo}.git",
                "installedAt": str(__import__("datetime").datetime.now().isoformat()),
            }
            _write_lock_sync(lock)
            return {"success": True, "repo": repo, "skill_name": skill_name}
        return {"success": False, "error": f"No SKILL.md found in {repo}/{skill_path}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(annotations=_MUTATING)
async def agy_install_skill_from_github(repo: str, skill_path: str = "", ctx: Any = None) -> dict:
    """Install a skill directly from a GitHub repository.

    Clones the repo temporarily and extracts the skill directory.

    ## Return Format
    {"success": bool, "repo": str, "skill_name": str}

    ## Examples
    agy_install_skill_from_github("sandraschi/python-expert")
    agy_install_skill_from_github("sandraschi/mcp-central-docs", "skills/fleet-expert")
    """
    import shutil
    import tempfile

    repo = repo.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if not repo or repo.count("/") != 1:
        return {"success": False, "error": f"Expected 'owner/repo', got {repo!r}"}

    tmpdir = tempfile.mkdtemp()
    try:
        # git clone blocks up to 60s — never on the event loop.
        await asyncio.to_thread(
            subprocess.run,
            [
                "git",
                "clone",
                "--depth",
                "1",
                f"https://github.com/{repo}.git",
                str(Path(tmpdir) / "repo"),
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"success": False, "error": str(e)}
    return await asyncio.to_thread(_install_from_github_sync, tmpdir, repo, skill_path)


# ── Version ───────────────────────────────────────────────────────────────────


@mcp.tool(annotations=_READ_ONLY)
async def agy_version(ctx: Any = None) -> dict:
    """Get the installed Antigravity CLI version.

    ## Return Format
    {"version": str, "path": str}
    """
    for candidate in ["agy", "antigravity"]:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {"version": result.stdout.strip(), "path": candidate}
        except FileNotFoundError:
            continue
    return {"version": "unknown", "path": "not found in PATH"}


# ── Help ──────────────────────────────────────────────────────────────────────


@mcp.tool(annotations=_READ_ONLY)
async def agy_help(ctx: Any = None) -> dict:
    """Show all available agy-mcp tools and usage."""
    return {
        "tools": [
            {"name": "agy_list_skills", "description": "List installed skills with source info"},
            {"name": "agy_read_skill", "description": "Read a skill's content"},
            {"name": "agy_search_skills", "description": "Search skill names and content"},
            {"name": "agy_install_skill", "description": "Create or update a skill"},
            {"name": "agy_delete_skill", "description": "Remove a skill"},
            {"name": "agy_get_config", "description": "Read full Antigravity config"},
            {"name": "agy_set_config", "description": "Set a config value"},
            {"name": "agy_list_providers", "description": "List configured LLM providers"},
            {"name": "agy_skill_lock_status", "description": "Read skill lock metadata"},
            {
                "name": "agy_install_skill_from_github",
                "description": "Install skill from GitHub repo",
            },
            {"name": "agy_version", "description": "Get AGY CLI version"},
        ],
        "skills_dir": str(_skills_dir()),
        "config_dir": str(_agents_dir()),
        "version": __version__,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
