"""Short code generation.

Codes are random strings over the 62-character alphabet [0-9a-zA-Z].
With 6 characters there are 62^6 ≈ 56.8 billion possible codes, so
collisions are rare; the caller retries on the rare clash.
"""

import re
import secrets
import string

ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
DEFAULT_LENGTH = 6

ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")

# Paths the app itself serves; a custom alias must not shadow them.
RESERVED = frozenset({"api", "docs", "redoc", "openapi.json", "static", "health", "favicon.ico"})


def generate_code(length: int = DEFAULT_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def validate_alias(alias: str) -> str | None:
    """Return an error message if the alias is not allowed, else None."""
    if not ALIAS_PATTERN.fullmatch(alias):
        return "Alias must be 3-32 characters: letters, digits, '-' or '_'."
    if alias.lower() in RESERVED:
        return f"'{alias}' is a reserved word."
    return None
