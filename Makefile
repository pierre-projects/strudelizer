# Thin wrapper around scripts/check.py, which works without make.
PYTHON ?= python

.PHONY: install check lint test strudel-check fixtures golden

install:
	$(PYTHON) -m pip install -e ".[all]"

check:
	$(PYTHON) scripts/check.py

lint:
	$(PYTHON) scripts/check.py lint

test:
	$(PYTHON) scripts/check.py test

strudel-check:
	$(PYTHON) scripts/check.py strudel

fixtures:
	$(PYTHON) tests/fixtures/make_fixtures.py

golden:
	STRUDELIZER_UPDATE_GOLDEN=1 $(PYTHON) -m pytest tests/test_golden.py
