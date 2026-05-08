.PHONY: install all clean

install:
	pip install -r requirements.txt

all: install
	@echo "Pipeline entrypoint - vul aan per issue."

clean:
	rm -rf data/processed/* models/* reports/figures/*
