#!/bin/sh
set -eu
python -m cardops_ai.app.migration_runner
if [ "${ALLOW_TEST_USER_SEEDING:-false}" = "true" ]; then
    python -m cardops_ai.scripts.seed_test_users
fi
