"""Bundled assets shipped with the wheel.

Files here are populated by hatchling's `force-include` at build time
(see pyproject.toml). The Python package only ships __init__.py — at
runtime, `importlib.resources.files("aegis._assets")` resolves to a
directory containing migrations/, profile.example.yaml, etc.
"""
