from __future__ import annotations

import os

# Point the app at a disposable test database *before* `takehome.config` (and
# anything that imports it) gets loaded, since `Settings()` is instantiated at
# import time. Tests that need a live Postgres (e.g. migration tests) use this
# database; it is never the dev/docker-compose database on 5433/5432.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://orbital:orbital@localhost:5555/orbital_test",
)
