#!/bin/sh
set -eu

python -m backend.app.migration_runner

if [ "${ALLOW_TEST_USER_SEEDING:-false}" = "true" ]; then
    echo "Seeding local test users..."
    python -m backend.scripts.seed_test_users
fi

exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

