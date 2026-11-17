"""Mint a development access token.

    uv run python -m app.core.security.cli --role admin
    uv run python -m app.core.security.cli --user-id <uuid>

Requires ``AUTH_JWT_SECRET`` in the environment or ``.env``.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from uuid import UUID, uuid4

from app.core.security.config import auth_settings
from app.core.security.tokens import Role, create_access_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a FinMind access token")
    parser.add_argument("--user-id", type=UUID, default=None)
    parser.add_argument("--role", choices=[r.value for r in Role], default="user")
    parser.add_argument("--ttl-minutes", type=int, default=None)
    args = parser.parse_args()

    user_id = args.user_id or uuid4()
    ttl = timedelta(minutes=args.ttl_minutes) if args.ttl_minutes else None
    token = create_access_token(auth_settings, user_id, Role(args.role), ttl=ttl)
    print(f"user_id: {user_id}")
    print(f"Authorization: Bearer {token}")


if __name__ == "__main__":
    main()
