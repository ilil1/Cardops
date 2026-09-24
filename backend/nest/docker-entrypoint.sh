#!/bin/sh
set -eu

python -m backend.app.migration_runner

if [ "${ALLOW_TEST_USER_SEEDING:-false}" = "true" ]; then
    python -m backend.scripts.seed_test_users
fi

if [ "${POC_SEED_ON_START:-false}" = "true" ]; then
    sh backend/render-seed.sh &
fi

exec node /app/backend/nest/dist/main.js
