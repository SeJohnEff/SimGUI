#!/bin/bash
# Run full quality checks: linting + tests with coverage
set -e
cd "$(dirname "$0")/.."

echo "=== Linting (ruff) ==="
python3 -m ruff check . || {
    echo "Lint errors found. Run 'make lint-fix' to auto-fix."
    exit 1
}
echo "OK"
echo ""

echo "=== Tests + Coverage ==="
python3 -m pytest tests/ \
    --cov=. \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    -v
echo ""
echo "Coverage report saved to htmlcov/index.html"
echo ""
echo "=== All checks passed ==="
