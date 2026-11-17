"""Shared test configuration.

Auth settings are read at import time, so test secrets are set here, before
any ``app`` module is imported by a test module.
"""

import os

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-do-not-use-in-production-0123456789")
os.environ.setdefault("AUTH_INTERNAL_SERVICE_TOKEN", "test-internal-token-0123456789")
