.PHONY: setup tests lint typecheck run-pre-commit

setup:
	uv sync

tests:
	uv run pytest .

lint:
	uv run ruff check .

typecheck:
	# notebooks/ has no .py files left (session 13 removed the last one,
	# fhir_match_data_source.py) - just evaluation/ to check.
	uv run mypy evaluation

run-pre-commit:
	uv run pre-commit run --all-files
