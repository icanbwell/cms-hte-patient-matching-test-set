.PHONY: setup tests lint typecheck run-pre-commit

setup:
	uv sync

tests:
	uv run pytest .

lint:
	uv run ruff check .

typecheck:
	# Separate invocations, not `mypy evaluation notebooks` - notebooks/ imports
	# evaluation/ as a package (`from evaluation.rule_eval import ...`) while
	# evaluation/'s own scripts import each other flat (`from rule_eval import ...`,
	# relying on PYTHONPATH=.). Checking both directories in one mypy run makes it
	# see rule_eval.py under two different module names and refuse to proceed.
	uv run mypy evaluation
	# --follow-imports=skip: fhir_match_data_source.py deliberately imports its
	# sibling modules two different ways (package-qualified vs a flat sys.path
	# fallback, for real Databricks execution) - correct at runtime, but it makes
	# mypy see the same file under two module names unless import-following is
	# disabled for this directory.
	uv run mypy --follow-imports=skip notebooks

run-pre-commit:
	uv run pre-commit run --all-files
