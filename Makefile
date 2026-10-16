# One command per thing a reviewer might want to do.
# `make all` goes from a fresh clone to every artefact in the repo.

PY      ?= python
DB      ?= warehouse.duckdb
RAW     ?= data/raw
SQLDIR  := 01-sql-retail-warehouse

.PHONY: help all data warehouse excel sql dq bench dbt python dashboard capstone test lint clean

help:
	@echo "make install    install pinned dependencies"
	@echo "make all        everything: data -> warehouse -> all five projects"
	@echo "make data       generate the synthetic warehouse CSVs (deterministic)"
	@echo "make warehouse  load the CSVs into DuckDB and build the views"
	@echo "make excel      project 0: rebuild the Excel business review workbook"
	@echo "make dq         run the data quality audit"
	@echo "make sql        run the ten analysis queries"
	@echo "make bench      run the query optimisation benchmark"
	@echo "make dbt        rebuild the same models with dbt and run its 59 tests"
	@echo "make python     project 2: fixture + analysis + charts"
	@echo "make dashboard  project 3: export the dashboard data"
	@echo "make capstone   project 4: churn model + experiment design"
	@echo "make test       run the pytest suite"
	@echo "make clean      remove generated data and build artefacts"

install:
	$(PY) -m pip install -r requirements.txt

all: data warehouse excel dq sql python dashboard capstone test

data:
	$(PY) src/generate_warehouse.py --out $(RAW) --sample-out data/sample --seed 42

warehouse: data
	$(PY) src/load_duckdb.py --db $(DB) --raw $(RAW)
	$(PY) -c "import duckdb,pathlib; c=duckdb.connect('$(DB)'); \
	  c.execute(pathlib.Path('$(SQLDIR)/sql/01_staging.sql').read_text()); \
	  print('staging views built')"

excel: warehouse
	$(PY) 00-excel-business-review/build_workbook.py --db $(DB)

dq: warehouse
	duckdb $(DB) < $(SQLDIR)/data_quality/profile.sql

sql: warehouse
	duckdb $(DB) < $(SQLDIR)/sql/02_analysis.sql

bench: warehouse
	$(PY) $(SQLDIR)/sql/bench.py --db $(DB) --scale 1
	$(PY) $(SQLDIR)/sql/bench.py --db $(DB) --scale 10

dbt:
	cd $(SQLDIR)/dbt && dbt build --profiles-dir .

python:
	$(PY) 02-python-pageviews/src/simulate_offline.py --out 02-python-pageviews/data
	$(PY) 02-python-pageviews/src/analyse.py

dashboard: warehouse
	$(PY) 03-dashboard-retention/src/export_dashboard_data.py --db $(DB)

capstone: warehouse
	$(PY) 04-capstone-churn/src/churn_model.py --db $(DB)
	PYTHONPATH=04-capstone-churn/src $(PY) 04-capstone-churn/src/design_winback_test.py --db $(DB)

test:
	$(PY) -m pytest tests/ -q

lint:
	ruff check src tests 00-excel-business-review 02-python-pageviews/src 03-dashboard-retention/src 04-capstone-churn/src

clean:
	rm -rf $(RAW) data/sample *.duckdb *.duckdb.wal
	rm -rf $(SQLDIR)/dbt/target $(SQLDIR)/dbt/logs
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
