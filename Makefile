PYTHON ?= python3

.PHONY: test research build

test:
	$(PYTHON) -m unittest discover -s tests -v

research:
	$(PYTHON) -m research.pipeline

build:
	pnpm build
