#!/bin/sh
set -eu

if [ "${POC_SEED_ON_START:-false}" != "true" ]; then
    exit 0
fi

echo "Running opt-in POC seed against the configured database..."
python -m cardops_ai.scripts.seed_test_users
python -m cardops_ai.scripts.import_customers
python -m cardops_ai.scripts.run_analysis_batch

if [ "${POC_SEED_CAMPAIGNS:-false}" = "true" ]; then
    python -m cardops_ai.scripts.seed_demo_campaign \
        --limit-per-campaign "${POC_SEED_LIMIT:-40}"
fi
