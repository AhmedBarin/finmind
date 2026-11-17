"""Shared Investor Agent test setup.

Settings require DATABASE_URL at import time. Unit and API tests never connect,
so a placeholder is enough; integration tests skip when the database is down.
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/finmind_test"
)
