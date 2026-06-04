"""Aegis CLI — subcommands for serve, init, up, down, migrate, doctor.

Designed for the `uv tool install aegis-agents` install path. Running
`aegis` with no arguments launches the MCP server (back-compat with the
old console-script entry).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aegis._assets import path as _asset_path
from aegis.config import AEGIS_HOME


# ─── Asset helpers ────────────────────────────────────────────────────────────

def _asset_bytes(name: str) -> bytes:
    return _asset_path(name).read_bytes()


def _compose_path() -> Path:
    return AEGIS_HOME / "compose.yml"


def _env_path() -> Path:
    return AEGIS_HOME / ".env"


def _profile_path() -> Path:
    return AEGIS_HOME / "profile.yaml"


# ─── Pretty output (no extra deps) ────────────────────────────────────────────

def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _step(msg: str) -> None:
    print(f"  → {msg}", flush=True)


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"  [warn] {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"  [error] {msg}", file=sys.stderr, flush=True)


# ─── Docker helpers ───────────────────────────────────────────────────────────

def _require_docker() -> None:
    if shutil.which("docker") is None:
        _err("docker not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop/")
        sys.exit(1)


def _compose(*args: str) -> int:
    return subprocess.call(["docker", "compose", "-f", str(_compose_path()), *args])


# ─── Subcommand: init ─────────────────────────────────────────────────────────

_ANSI_ESC_RE = re.compile(r"\x1b(?:\[[0-9;?]*[@-~]|O[A-Z])")
_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_prompt_input(s: str) -> str:
    """Strip ANSI escape sequences (arrow keys etc.) and bare control bytes.

    getpass() doesn't do line editing, so cursor-movement keystrokes land
    in the input verbatim. For tokens/keys (printable ASCII only), this
    is always wrong; for usernames, also always wrong.
    """
    s = _ANSI_ESC_RE.sub("", s)
    s = _CTRL_CHARS_RE.sub("", s)
    return s.strip()


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"  {label}{suffix}: "
    val = getpass.getpass(prompt) if secret else input(prompt)
    return _sanitize_prompt_input(val) or default


def _write_env(api_key: str, gh_token: str, gh_user: str) -> None:
    lines = [
        "# Aegis configuration — written by `aegis init`.",
        "# Edit values here; re-run `aegis init` to regenerate.",
        "",
        "AEGIS_ENV=local",
        "LOG_LEVEL=INFO",
        "",
        f"ANTHROPIC_API_KEY={api_key}",
        "AEGIS_LLM_MODEL=claude-sonnet-4-5",
        "AEGIS_LLM_MAX_COST_USD_PER_RUN=0.50",
        "AEGIS_LLM_MAX_COST_USD_PER_DAY=5.0",
        "",
        f"AEGIS_PROFILE_PATH={_profile_path()}",
        "",
        f"GITHUB_TOKEN={gh_token}",
        f"GITHUB_USERNAME={gh_user}",
        "",
        "DATABASE_URL=postgresql://aegis:aegis@localhost:5432/aegis",
        "REDIS_URL=redis://localhost:6379/0",
        "",
    ]
    path = _env_path()
    path.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)


def cmd_init(args: argparse.Namespace) -> int:
    _say()
    _say("  Aegis setup")
    _say(f"  Config dir: {AEGIS_HOME}")
    _say()

    AEGIS_HOME.mkdir(parents=True, exist_ok=True)

    if _env_path().exists() and not args.force:
        _warn(f"{_env_path()} already exists. Re-run with --force to overwrite.")
        return 1

    _require_docker()

    _say("  Anthropic API key is required. Get one at https://console.anthropic.com/")
    api_key = _prompt("ANTHROPIC_API_KEY", secret=True)
    if not api_key:
        _err("ANTHROPIC_API_KEY is required.")
        return 1

    _say()
    _say("  Optional: GitHub token for the daily briefing (leave blank to skip).")
    _say("  Generate at https://github.com/settings/tokens — classic needs the")
    _say("  'notifications' scope; fine-grained needs 'Notifications: Read'.")
    gh_token = _prompt("GITHUB_TOKEN (optional)", secret=True)
    gh_user = _prompt("GITHUB_USERNAME (optional)") if gh_token else ""

    _step(f"Writing {_env_path()}")
    _write_env(api_key, gh_token, gh_user)

    _step(f"Writing {_compose_path()}")
    _compose_path().write_bytes(_asset_bytes("compose.toolmode.yml"))

    if not _profile_path().exists():
        _step(f"Writing {_profile_path()} (edit this to personalise fit scoring)")
        _profile_path().write_bytes(_asset_bytes("profile.example.yaml"))
    else:
        _ok(f"{_profile_path()} already exists, leaving it alone")

    _say()
    _ok("Configuration written.")
    _say()
    _say("  Next steps:")
    _say("    1. aegis up                    # start Postgres + Redis, run migrations")
    _say("    2. claude mcp add aegis -- aegis serve")
    _say("    3. Restart Claude Desktop / Claude Code; Aegis tools appear under the connector menu.")
    _say()
    _say(f"  Edit {_profile_path()} to tune fit scoring for your skills and roles.")
    _say()
    return 0


# ─── Subcommand: up ───────────────────────────────────────────────────────────

async def _wait_for_postgres(timeout_s: int = 30) -> bool:
    import asyncpg

    from aegis.config import settings

    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(settings.database_url)
            await conn.close()
            return True
        except (OSError, asyncpg.PostgresError) as e:
            last_err = e
            await asyncio.sleep(1)
    if last_err:
        _err(f"Postgres not ready after {timeout_s}s: {last_err}")
    return False


def cmd_up(_args: argparse.Namespace) -> int:
    del _args
    _require_docker()
    if not _compose_path().exists():
        _err(f"{_compose_path()} not found. Run `aegis init` first.")
        return 1

    _step("Starting Postgres + Redis")
    rc = _compose("up", "-d")
    if rc != 0:
        return rc

    _step("Waiting for Postgres")
    if not asyncio.run(_wait_for_postgres()):
        return 1
    _ok("Postgres ready")

    _step("Applying migrations")
    from aegis.db.migrate import run_migrations_sync
    newly, total = run_migrations_sync()
    _ok(f"Migrations: {newly} newly applied, {total} total")

    _say()
    _ok("Aegis is up. Run `aegis serve` or wire it into Claude with:")
    _say("    claude mcp add aegis -- aegis serve")
    return 0


# ─── Subcommand: down ─────────────────────────────────────────────────────────

def cmd_down(_args: argparse.Namespace) -> int:
    del _args
    _require_docker()
    if not _compose_path().exists():
        _err(f"{_compose_path()} not found. Run `aegis init` first.")
        return 1
    return _compose("down")


# ─── Subcommand: migrate ──────────────────────────────────────────────────────

def cmd_migrate(_args: argparse.Namespace) -> int:
    del _args
    from aegis.db.migrate import run_migrations_sync
    newly, total = run_migrations_sync()
    _ok(f"Migrations: {newly} newly applied, {total} total")
    return 0


# ─── Subcommand: doctor ───────────────────────────────────────────────────────

def cmd_doctor(_args: argparse.Namespace) -> int:
    del _args
    from aegis.config import settings

    _say()
    _say("  Prerequisites:")
    if shutil.which("docker"):
        _ok("docker")
    else:
        _warn("docker missing — https://www.docker.com/products/docker-desktop/")

    _say()
    _say("  Config:")
    if _env_path().exists():
        _ok(f"{_env_path()}")
    else:
        _warn(f"{_env_path()} missing — run `aegis init`")
    if _compose_path().exists():
        _ok(f"{_compose_path()}")
    else:
        _warn(f"{_compose_path()} missing — run `aegis init`")
    if _profile_path().exists():
        _ok(f"{_profile_path()}")
    else:
        _warn(f"{_profile_path()} missing — run `aegis init`")

    _say()
    _say("  Settings:")
    for warning in settings.check():
        _warn(warning.strip())
    if not settings.check():
        _ok("all required settings present")
    _say()
    return 0


# ─── Subcommand: serve ────────────────────────────────────────────────────────

def cmd_serve(_args: argparse.Namespace) -> int:
    del _args  # uniform callback signature; serve takes no flags
    from aegis.mcp_server import main as serve_main
    serve_main()
    return 0


# ─── Subcommand: api ──────────────────────────────────────────────────────────

def cmd_api(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run(
        "aegis.app:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


# ─── Entry point ──────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aegis",
        description="Aegis — local-first, MCP-native multi-agent platform.",
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("serve", help="Run the MCP server (stdio).")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("init", help="Interactive first-time setup.")
    sp.add_argument("--force", action="store_true", help="Overwrite existing .env")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("up", help="Start Postgres + Redis and apply migrations.")
    sp.set_defaults(func=cmd_up)

    sp = sub.add_parser("down", help="Stop Postgres + Redis (data preserved).")
    sp.set_defaults(func=cmd_down)

    sp = sub.add_parser("migrate", help="Apply pending SQL migrations.")
    sp.set_defaults(func=cmd_migrate)

    sp = sub.add_parser("doctor", help="Check prerequisites and config.")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser(
        "api",
        help="Run the REST API + trace viewer (http://localhost:8000/docs).",
    )
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(func=cmd_api)

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        # Back-compat: bare `aegis` (e.g. from existing Claude Desktop configs) runs the server.
        sys.exit(cmd_serve(args))
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
