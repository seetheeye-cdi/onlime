"""macOS Keychain integration for secret management."""

from __future__ import annotations

import subprocess

_SERVICE = "onlime"

# In-memory cache: secrets don't change during daemon lifetime.
# Protects against macOS Keychain lock after sleep.
_cache: dict[str, str] = {}


def get_secret(account: str, service: str = _SERVICE) -> str:
    """Load a secret from macOS Keychain (cached after first lookup)."""
    cache_key = f"{service}/{account}"
    if cache_key in _cache:
        return _cache[cache_key]
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Keychain lookup failed: {service}/{account}")
    val = result.stdout.strip()
    _cache[cache_key] = val
    return val


def set_secret(account: str, password: str, service: str = _SERVICE) -> None:
    """Store a secret in macOS Keychain."""
    subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-s", service, "-a", account, "-w", password, "-U"],
        check=True,
    )


def get_secret_or_env(account: str, env_var: str | None = None) -> str:
    """Try Keychain first, fall back to environment variable."""
    import os

    try:
        return get_secret(account)
    except RuntimeError:
        if env_var:
            val = os.environ.get(env_var, "")
            if val:
                return val
        raise
