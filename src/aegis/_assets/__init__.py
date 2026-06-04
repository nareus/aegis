"""Bundled assets shipped with the wheel.

Files here are populated by hatchling's `force-include` at build time
(see pyproject.toml). When installed from a wheel, `path(name)` resolves
to files inside this package directory. When running from a source
checkout (where force-include hasn't run), it falls back to the
conventional repo-root locations so dev workflow stays usable.
"""

from pathlib import Path


def path(name: str) -> Path:
    """Resolve an asset name to a real Path.

    Works in two modes:
    - Wheel install: file lives in this package directory (force-included).
    - Source checkout: file lives at repo root (profile.example.yaml,
      migrations/) or already inside this package (compose.toolmode.yml).
    """
    pkg_dir = Path(__file__).resolve().parent

    # 1. Wheel install — or files committed directly to src/aegis/_assets/
    direct = pkg_dir / name
    if direct.exists():
        return direct

    # 2. Source checkout — files at repo root per pyproject.toml force-include
    repo_root = pkg_dir.parent.parent.parent
    fallback = repo_root / name
    if fallback.exists():
        return fallback

    raise FileNotFoundError(f"Asset not found: {name}")
