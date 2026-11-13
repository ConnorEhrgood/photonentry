import os

if os.environ.get("PHOTONENTRY_DB_TESTS"):
    # The store tests also run on Postgres, with the database suite's fixtures (migration, cleaning, the LISTEN thread).
    from tests.db.conftest import clean, listener, schema  # noqa: F401
