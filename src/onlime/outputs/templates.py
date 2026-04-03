"""Jinja2 template engine for Obsidian note generation."""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Templates directory at project root
_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


@lru_cache(maxsize=1)
def get_jinja_env() -> Environment:
    """Get configured Jinja2 environment."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(template_name: str, **context) -> str:
    """Render a Jinja2 template with given context."""
    env = get_jinja_env()
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)
