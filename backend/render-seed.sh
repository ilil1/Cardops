#!/bin/sh
set -eu

if [ "${POC_SEED_ON_START:-false}" != "true" ]; then
    exit 0
fi

echo "Running opt-in POC seed against the configured database..."
python -m backend.scripts.seed_test_users
python -m backend.scripts.import_customers
python -m backend.scripts.run_analysis_batch

if [ "${POC_SEED_CAMPAIGNS:-false}" = "true" ]; then
    python -m backend.scripts.seed_demo_campaign \
        --limit-per-campaign "${POC_SEED_LIMIT:-40}"
fi
