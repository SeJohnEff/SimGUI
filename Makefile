.PHONY: test lint lint-fix coverage check clean release

.venv:
	python3 -m venv .venv

test: .venv
	.venv/bin/python -m pip install -r requirements-dev.txt
	.venv/bin/python -m pytest -x -q --cov=. --cov-report=term

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

release:
	@VERSION=$$(python3 -c "from version import __version__; print(__version__)") && \
	echo "Releasing version $$VERSION..." && \
	git diff --quiet || (echo "ERROR: Uncommitted changes. Commit first." && exit 1) && \
	git tag -a "v$$VERSION" -m "Release v$$VERSION" && \
	git push && \
	git push --tags && \
	echo "Released v$$VERSION"