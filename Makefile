.PHONY: test lint lint-fix coverage check clean

test:
	python3 -m pytest tests/ -v

lint:
	python3 -m ruff check .

lint-fix:
	python3 -m ruff check --fix .

coverage:
	python3 -m pytest tests/ \
		--cov=. \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		-v

check: lint coverage
	@echo ""
	@echo "=== All checks passed ==="

clean:
	rm -rf htmlcov .coverage __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
