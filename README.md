# FinPulse

FinPulse is a FastAPI + PostgreSQL research platform for public-company risk monitoring.
It ingests SEC filings and related market data, processes and stores structured evidence,
computes multi-layer risk signals, and exposes the results through a read-only HTTP API.

At a high level, the project answers one question:

`How is a company's public narrative, financial profile, insider behavior, market behavior, and external coverage changing over time?`

## What FinPulse Does

FinPulse combines six data sources into one research workflow:

- SEC EDGAR filings (`10-K`, `10-Q`) for narrative sections and filing metadata
- SEC XBRL facts for structured financial statements
- SEC Form 4 filings for insider transactions
- Mistral embeddings for semantic text comparison
- Yahoo Finance market history for daily OHLCV pricing
- Google News RSS and FRED for external news and macro context

Those sources feed a layered signal engine:

- Text layer: filing-language drift and forward-looking tone
- Numeric layer: margin deterioration, growth slowdown, leverage stress, earnings quality, anomaly detection
- Behavior layer: insider selling asymmetry and concentration
- Market layer: price momentum, volatility, valuation stretch
- Sentiment layer: news-tone deterioration and news-volume spikes

The signal layers are fused into a composite score called `nci_global`, which is stored historically and served by the API.

## Core Architecture

The repo is organized around a pipeline-first design:

1. Ingest raw source data into local storage and PostgreSQL.
2. Split filings into sections and parse XBRL/Form 4/news records.
3. Generate paragraph embeddings for filing sections.
4. Compute named per-filing signal rows and composite NCI snapshots.
5. Expose the latest company snapshot and time-series data through FastAPI.

The API is read-only. It does not recompute signals on demand. It serves data already written by the pipelines into tables such as `companies`, `filings`, `filing_sections`, `xbrl_facts`, `insider_transactions`, `news_items`, `market_prices`, `signal_scores`, and `nci_scores`.

## Data Sources

| Source | Module | Purpose |
| --- | --- | --- |
| SEC EDGAR | `ingestion/edgar_client.py` | Company metadata, filing lists, filing text, company facts |
| SEC Form 4 XML | `ingestion/form4_client.py` + `processing/form4_parser.py` | Insider transaction extraction |
| Mistral Embeddings API | `processing/embeddings.py` | Semantic similarity and paragraph-level text features |
| Google News RSS | `ingestion/news_client.py` | Recent company news and external narrative |
| Yahoo Finance chart API | `ingestion/market_client.py` | Daily market price and volume history |
| FRED API | `ingestion/fred_client.py` | Macro observations such as CPI, rates, unemployment, VIX, and credit spread proxy |

## Pipelines

The project is built around explicit runnable pipelines.

### Filing pipeline

Main module:

- `pipelines/filing_pipeline.py`

What it does:

- Ingests `10-K` or `10-Q` filings for one company
- Splits filing text into sections
- Parses XBRL facts
- Generates embeddings
- Runs the signal stack for each selected filing

Common example:

```powershell
py -m pipelines.filing_pipeline --ticker NKLA --form 10-K --max 5
py -m pipelines.filing_pipeline --ticker NKLA --form 10-Q --max 12
```

### Form 4 pipeline

Entry points:

- `run_form4_pipeline.py`
- `pipelines/form4_pipeline.py`

What it does:

- Ingests Form 4 / 4-A filings
- Parses insider transactions
- Deduplicates and stores them in `insider_transactions`

### News pipeline

Main module:

- `pipelines/run_news_pipeline.py`

What it does:

- Resolves a company
- Fetches recent RSS items
- Normalizes and stores them in `news_items`

Example:

```powershell
py -m pipelines.run_news_pipeline --ticker NKLA --limit 50
```

### Market pipeline

Main module:

- `pipelines/run_market_pipeline.py`

What it does:

- Fetches daily market history for a symbol
- Stores OHLCV rows in `market_prices`

Example:

```powershell
py -m pipelines.run_market_pipeline --ticker NKLA --symbol NKLA --start 2020-01-01 --end 2026-04-18
```

### Macro pipeline

Main module:

- `pipelines/run_macro_pipeline.py`

What it does:

- Fetches a small default FRED macro basket
- Stores rows in `macro_observations`

Default macro series:

- `CPIAUCSL`
- `FEDFUNDS`
- `DGS10`
- `UNRATE`
- `INDPRO`
- `VIXCLS`
- `BAA10Y`

Example:

```powershell
py -m pipelines.run_macro_pipeline --start 2015-01-01
```

### Full backfill pipeline

Entry points:

- `run_backfill_company.py`
- `pipelines/run_backfill_company.py`

What it does:

- Orchestrates the end-to-end backfill for one company
- Pulls annual and quarterly filings
- Runs section splitting, embeddings, XBRL parsing, Form 4 ingestion, news, market, macro, and optional signals

### Signals pipeline

Entry points:

- `run_signals.py`
- `pipelines/signals_pipeline.py`

What it does:

- Computes the named signal rows for a filing anchor
- Writes `signal_scores`
- Writes the richer `nci_scores` snapshot used by the API and charts

## Signal System

The modern signal implementation lives under [`signals/`](./signals).

Primary layer modules:

- `signals/text_signals.py`
- `signals/numeric_signals.py`
- `signals/behavior_signals.py`
- `signals/market_signals.py`
- `signals/sentiment_signals.py`
- `signals/composite_engine.py`
- `signals/catalog.py`

Main signals currently represented in the repo:

- `rlds`: Risk Lexical Drift Score for Risk Factors
- `mda_drift`: drift score for Management Discussion & Analysis
- `forward_pessimism`: forward-looking tone shift toward caution
- `fundamental_deterioration`: margin-based profitability stress
- `revenue_growth_deceleration`: slowing top-line growth
- `balance_sheet_stress`: leverage, cash, and cash-flow quality stress
- `earnings_quality`: accrual-based quality warning
- `numeric_anomaly`: deviation from the company's own history
- `ita`: insider transaction asymmetry
- `insider_concentration`: breadth of opportunistic selling
- `insider_signal`: combined behavior-layer score
- `market_signal`: combined price, volatility, and optional valuation stress
- `sentiment_signal`: combined news-tone and volume stress
- `nci_global`: final composite score

Compatibility shims remain in the older signal files so legacy imports still work while the cleaner layer modules hold the current formulas.

More detail is documented in [`signals/README.md`](./signals/README.md).

## API Layer

FastAPI entry point:

- `main.py`

Versioned router:

- `app/api/v1/router.py`

Current endpoint groups:

- `GET /health`
- `GET /api/v1/health`
- `GET /api/v1/score/{ticker}`
- `GET /api/v1/signals/{ticker}`
- `GET /api/v1/signals/{ticker}/history`
- `GET /api/v1/filings/{ticker}`

The score endpoint returns the latest high-level company snapshot, including:

- company metadata
- latest annual and quarterly filings
- latest named signals
- XBRL summary values such as revenue and net income
- insider summary
- latest market snapshot
- recent news
- data freshness flags

Detailed API field-level documentation lives in [`app/api/README.md`](./app/api/README.md).

## Database and Schema

Database stack:

- PostgreSQL with `pgvector`
- Redis is included in `docker-compose.yml` for queue/cache support
- Adminer is included for quick DB inspection

Schema management:

- Alembic migrations live under [`alembic/`](./alembic)
- SQLAlchemy models live under [`app/db/models/`](./app/db/models)
- [`schema.sql`](./schema.sql) is a live schema snapshot generated from the current PostgreSQL database

Important note:

- `schema.sql` is useful as a current reference for the live database
- Alembic migrations and SQLAlchemy models remain the source of truth for ongoing development

## Repository Tree

This is the current high-level shape of the repo:

```text
PI/
|-- alembic/
|   |-- env.py
|   `-- versions/
|-- app/
|   |-- api/
|   |   |-- README.md
|   |   `-- v1/
|   |-- core/
|   `-- db/
|       |-- models/
|       |-- base.py
|       `-- session.py
|-- data/
|   `-- raw/
|-- ingestion/
|   |-- edgar_client.py
|   |-- form4_client.py
|   |-- fred_client.py
|   |-- market_client.py
|   |-- news_client.py
|   `-- *_repo.py
|-- pipelines/
|   |-- filing_pipeline.py
|   |-- form4_pipeline.py
|   |-- ingestion_pipeline.py
|   |-- run_backfill_company.py
|   |-- run_macro_pipeline.py
|   |-- run_market_pipeline.py
|   |-- run_news_pipeline.py
|   |-- signals_pipeline.py
|   |-- text_pipeline.py
|   `-- xbrl_pipeline.py
|-- processing/
|   |-- embeddings.py
|   |-- filing_splitter.py
|   |-- form4_parser.py
|   |-- news_normalizer.py
|   `-- xbrl_parser.py
|-- signals/
|   |-- README.md
|   |-- behavior_signals.py
|   |-- catalog.py
|   |-- composite_engine.py
|   |-- market_signals.py
|   |-- numeric_signals.py
|   |-- sentiment_signals.py
|   `-- text_signals.py
|-- Tests/
|-- docker-compose.yml
|-- main.py
|-- pipeline.py
|-- requirements.txt
|-- run_backfill_company.py
|-- run_form4_pipeline.py
|-- run_signals.py
`-- schema.sql
```

## Getting Started

### 1. Start infrastructure

```powershell
docker compose up -d
```

This starts:

- PostgreSQL with `pgvector`
- Redis
- Adminer

### 2. Create and activate a virtual environment

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment variables

Create or update `.env` with the keys used by [`app/core/config.py`](./app/core/config.py), especially:

- PostgreSQL connection settings
- EDGAR user-agent identity
- Mistral API key and model
- FRED API key
- optional storage and Redis settings

### 5. Apply migrations

```powershell
alembic upgrade head
```

### 6. Run the API

```powershell
py -m uvicorn main:app --reload --port 8000
```

Useful local URLs:

- `http://localhost:8000/health`
- `http://localhost:8000/api/v1/score/NKLA`
- `http://localhost:8000/api/v1/signals/NKLA/history`
- `http://localhost:8000/docs`

## Typical Workflows

### Backfill one company end to end

```powershell
py run_backfill_company.py --ticker NKLA --symbol NKLA --ten-k-max 5 --ten-q-max 12 --form4-max 50 --news-limit 50 --market-start 2020-01-01 --market-end 2026-04-18 --macro-start 2015-01-01
```

### Recompute filing-anchored signals for an existing filing

```powershell
py run_signals.py --filing-id 123
```

### Process filings already present in the database

```powershell
py -m pipelines.filing_pipeline --ticker NKLA --form 10-K --max 5 --skip-ingest
py -m pipelines.filing_pipeline --ticker NKLA --form 10-Q --max 12 --skip-ingest
```

## Tests

The repo already includes pytest coverage for the main layers:

- API behavior
- DB connectivity
- filing splitting
- embeddings
- XBRL parsing
- Form 4 parsing
- market/news/macro pipelines
- signal computation
- company backfill orchestration

Run tests with:

```powershell
pytest
```

## Current Project State

The project already has:

- a working ingestion and processing stack for filings, XBRL, Form 4, news, market, and macro data
- a cleaned modern signal architecture under `signals/`
- a composite NCI layer stored historically in `nci_scores`
- a read-only FastAPI layer for querying score snapshots and filing/signal history
- a live `schema.sql` snapshot that matches the current database

Current practical notes:

- Signals are filing-anchored, so charts typically use filing time on the x-axis and score on the y-axis
- Macro observations are ingested and stored, but macro is currently a supporting dataset rather than the main driver of the published NCI formula
- The API reads existing DB state; if a ticker has no signals yet, you need to run the relevant pipelines first

## License / Publishing Note

Before pushing to GitHub, review:

- `.env` is ignored by `.gitignore`, but already-tracked secrets must still be removed from Git history if they were ever committed
- `data/raw/` is ignored to keep large SEC source files out of the repository
- `schema.sql` is intentionally kept so the live database shape is documented in the repo
