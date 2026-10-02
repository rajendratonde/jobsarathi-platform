"""Secret references.

Configuration never holds a secret in a code default. A setting may hold the
secret value directly (local development, from an untracked .env file) or a
reference that is resolved at start-up:

    env:NAME            read environment variable NAME
    file:/path          read a file (e.g. a mounted container secret)

Cloud secret stores are deliberately not implemented: which AWS store is used
is still TBD (T1). A reference with an unknown scheme fails loudly instead of
being treated as a literal password.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

KNOWN_SCHEMES = ("env:", "file:")


class SecretResolutionError(RuntimeError):
    pass


def is_reference(value: str) -> bool:
    return value.startswith(KNOWN_SCHEMES) or (":" in value and value.split(":", 1)[0] in {"aws-sm", "aws-ssm", "vault"})


def resolve(value: SecretStr | str | None) -> SecretStr | None:
    """Resolve a secret value or reference. Never logs the result."""
    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if raw.startswith("env:"):
        name = raw[4:]
        resolved = os.environ.get(name)
        if resolved is None:
            raise SecretResolutionError(f"Secret reference env:{name} is not set")
        return SecretStr(resolved)
    if raw.startswith("file:"):
        path = Path(raw[5:])
        if not path.is_file():
            raise SecretResolutionError(f"Secret reference file:{path} does not exist")
        return SecretStr(path.read_text(encoding="utf-8").strip())
    scheme = raw.split(":", 1)[0] if ":" in raw else ""
    if scheme in {"aws-sm", "aws-ssm", "vault"}:
        raise SecretResolutionError(
            f"Secret store '{scheme}' is not available yet (secret store product is TBD); use env: or file:")
    return SecretStr(raw)
