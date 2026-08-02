"""
Root fixtures — deliberately EMPTY of database wiring.

`tests/unit` must be runnable with no connection string, no engine and no live
Supabase project, so that the rules encoded there (the onboarding derivation,
the rate limiter) can be asserted on a fork, in a fresh clone, or in CI without
secrets. Importing `app.core.db` here would build an engine at collection time
and defeat that for every test in the tree.

The database fixtures live in `tests/integration/conftest.py`, which only
applies to the tests that genuinely need them.
"""
