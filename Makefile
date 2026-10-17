PYTHON ?= python
STRUDEL_DIR = tests/strudel

.PHONY: install strudel-deps strudel-check test golden fixtures ci

install:
	$(PYTHON) -m pip install -e ".[dev]"

# Pinned Strudel runtime (@strudel/* 1.2.6, exact versions in package-lock.json)
strudel-deps:
	npm ci --prefix $(STRUDEL_DIR)

# Evaluate every golden .js in Strudel and query its first cycles
strudel-check: strudel-deps
	cd $(STRUDEL_DIR) && node validate.mjs --cycles 8 ../fixtures/*.js ../fixtures/ir/*.js > /dev/null && echo "strudel-check: all files evaluate"

test:
	$(PYTHON) -m pytest

# Regenerate MIDI fixtures, then golden .ir.json/.js files (review the diff!)
fixtures:
	$(PYTHON) tests/fixtures/make_fixtures.py

golden:
	STRUDELIZER_UPDATE_GOLDEN=1 $(PYTHON) -m pytest tests/test_golden.py

ci: install strudel-deps test
