"""ASGI entrypoint for the restart harness.

Serves the ordinary walking-skeleton app on a file-backed store, so a
subprocess running this module can be killed outright and a fresh one started
on exactly the same state. No production code changes: build_app already
accepts a store."""

import os

from lalfita.common.store import JsonFileStore
from lalfita.local import build_app

STORE_PATH = os.environ.get("LALFITA_STORE_PATH", "/tmp/lalfita-durability.json")

app, ctx = build_app(store=JsonFileStore(STORE_PATH))
