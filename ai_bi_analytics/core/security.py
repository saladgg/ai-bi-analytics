"""
API-key authentication (audit SEC-8).

Clients are configured as ``API_KEYS=client_id:sha256hex,...``: the
server stores only SHA-256 hashes, every client has its own identity (for
rate limiting and logs), and a key is rotated by listing the new entry
next to the old one until clients have switched. The legacy single
``API_KEY`` still works and authenticates as client ``default``.

Generate a key and its entry::

    python -m ai_bi_analytics.core.security <client_id>
"""

import hashlib
import hmac
import re
import secrets
import sys
from dataclasses import dataclass

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LEGACY_CLIENT_ID = "default"
MIN_KEY_LENGTH = 32
PLACEHOLDER_KEYS = frozenset(
    {"change-me", "changeme", "your-key-here", "secret", "test", "password"}
)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    client_id: str


def hash_api_key(key: str) -> str:
    # Keys are high-entropy random tokens, so a fast hash is appropriate:
    # there is nothing to brute-force a dictionary against.
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def parse_api_key_entry(entry: str) -> tuple[str, str]:
    client_id, sep, digest = entry.partition(":")
    client_id, digest = client_id.strip(), digest.strip().lower()
    if not sep or not CLIENT_ID_PATTERN.match(client_id):
        raise ValueError(f"invalid API_KEYS client id in entry {entry[:20]!r}")
    if not SHA256_HEX_PATTERN.match(digest):
        raise ValueError(f"API_KEYS entry for {client_id!r} must be a sha256 hex")
    return client_id, digest


class ApiKeyStore:
    def __init__(self, entries: list[tuple[str, str]]) -> None:
        self._entries = tuple(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def authenticate(self, presented: str | None) -> Principal | None:
        """
        Compares against every entry, without stopping at a match, so the
        response time doesn't reveal which (or whether an) entry matched.
        """
        if not presented:
            return None
        digest = hash_api_key(presented)
        match: str | None = None
        for client_id, expected in self._entries:
            if hmac.compare_digest(digest, expected) and match is None:
                match = client_id
        return Principal(match) if match is not None else None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not CLIENT_ID_PATTERN.match(args[0]):
        print("usage: python -m ai_bi_analytics.core.security <client_id>")  # noqa: T201
        return 2
    key = generate_api_key()
    print(f"API key for {args[0]} (give this to the client, store it nowhere else):")  # noqa: T201
    print(f"  {key}")  # noqa: T201
    print("Add to API_KEYS on the server:")  # noqa: T201
    print(f"  {args[0]}:{hash_api_key(key)}")  # noqa: T201
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
