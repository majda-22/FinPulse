# FinPulse API

This folder contains the HTTP API for FinPulse.

The API supports both:
- read endpoints for data already written to PostgreSQL
- execution endpoints that trigger existing pipelines as background jobs

## Base URLs

- Health check: `/health`
- Versioned health check: `/api/v1/health`
- Versioned API root: `/api/v1`
- Interactive docs: `/docs`

Example local server command:

```powershell
py -m uvicorn main:app --reload --port 8000
```

## Endpoint Summary

### `GET /api/v1/companies`

Purpose:
- Return company identities currently stored in the database
- Useful when the client needs names, tickers, and CIKs together

Query parameters:
- `active_only`: optional boolean filter, default `false`
- `limit`: max rows to return, default `1000`, max `10000`

Response fields per row:
- `name`
- `ticker`
- `cik`
- `is_active`

Typical response:

```json
[
  {
    "name": "Apple Inc.",
    "ticker": "AAPL",
    "cik": "0000320193",
    "is_active": true
  },
  {
    "name": "Nikola Corporation",
    "ticker": "NKLA",
    "cik": "0001731289",
    "is_active": true
  }
]
```

### `GET /api/v1/companies/tickers`

Purpose:
- Return the list of company tickers currently stored in the database
- Useful for dropdowns, autocomplete, or checking which companies are already ingested

Query parameters:
- `active_only`: optional boolean filter, default `false`
- `limit`: max rows to return, default `1000`, max `10000`

Response:
- plain JSON array of ticker strings

Example:

```text
/api/v1/companies/tickers
/api/v1/companies/tickers?active_only=true
```

Typical response:

```json
["AAPL", "AMZN", "MSFT", "NKLA", "TSLA"]
```

### `GET /api/v1/companies/ticker-by-name`

Purpose:
- Return the ticker for a company name
- Useful when the client knows the company name but not the ticker yet

Query parameters:
- `name`: company name to resolve

Behavior:
- tries a case-insensitive exact match first
- if there is no exact match, tries a partial name match
- if multiple partial matches exist, returns a `409` with candidate companies

Examples:

```text
/api/v1/companies/ticker-by-name?name=Apple%20Inc.
/api/v1/companies/ticker-by-name?name=Nikola%20Corporation
```

Typical response:

```json
"AAPL"
```

### `POST /api/v1/pipelines/backfill/company`

Purpose:
- Run the full company backfill workflow through the API
- This orchestrates filings, Form 4, news, market, macro, and optional signal scoring

Body fields:
- `identifier`: ticker, full company name, or CIK
- `ten_k_max`
- `ten_q_max`
- `form4_max`
- `form4_parse_limit`
- `news_limit`
- `symbol`
- `filing_start`
- `filing_end`
- `market_start`
- `market_end`
- `macro_start`
- `macro_end`
- `macro_series`
- `run_signals`

Behavior:
- returns `202 Accepted`
- starts a background job
- returns a `job_id` and `status_url`

Example:

```json
POST /api/v1/pipelines/backfill/company
{
  "identifier": "NKLA",
  "ten_k_max": 5,
  "ten_q_max": 12,
  "form4_max": 50,
  "news_limit": 50,
  "market_start": "2020-01-01",
  "macro_start": "2015-01-01",
  "run_signals": true
}
```

### `POST /api/v1/pipelines/signals/company`

Purpose:
- Run the full signal stack for all qualifying filings of one company
- Useful after fixing signal logic or after re-embedding/reparsing data

Body fields:
- `identifier`: ticker, full company name, or CIK
- `form_types`: optional list of filing forms, defaults to `10-K` and `10-Q`
- `limit`: optional limit on how many filings to process

Behavior:
- returns `202 Accepted`
- executes the signal batch in the background
- current runner support is limited to `10-K` and `10-Q`

### `POST /api/v1/pipelines/signals/filing/{filing_id}`

Purpose:
- Run the signal pipeline for one specific filing id
- Useful for targeted debugging and recomputation

Behavior:
- currently accepts only `10-K` and `10-Q`
- returns `202 Accepted`
- stores the result under a background job id

### `GET /api/v1/pipelines/jobs/{job_id}`

Purpose:
- Poll the current status of a background pipeline job

Response fields:
- `job_id`
- `pipeline_name`
- `status`
- `submitted_at`
- `started_at`
- `finished_at`
- `status_url`
- `request`
- `result`
- `error`

Typical statuses:
- `queued`
- `running`
- `completed`
- `failed`

### `GET /health`

Purpose:
- Confirm the FastAPI service is running
- Confirm the database connection is available

Response fields:
- `status`: API status string, currently `"ok"`
- `db`: database status, usually `"connected"` or `"error"`
- `version`: API version string

Typical response:

```json
{
  "status": "ok",
  "db": "connected",
  "version": "1.0.0"
}
```

### `GET /api/v1/score/{ticker}`

Purpose:
- Return the main high-level company snapshot for one ticker
- This is the best endpoint for a company profile or dashboard card

Path parameter:
- `ticker`: company identifier

Accepted identifier formats:
- ticker, for example `AAPL`
- full company name, for example `Apple Inc.`
- CIK, for example `0000320193`

Main response fields:
- `ticker`: normalized company ticker
- `company_name`: company name from `companies`
- `sector`: company sector if available
- `composite_risk_score`: latest top-level composite score
- `risk_label`: risk bucket derived from the composite score
- `latest_annual_filing`: latest `10-K` or `10-K/A`
- `latest_quarterly_filing`: latest `10-Q` or `10-Q/A`
- `signals`: latest available row for each signal name
- `xbrl_summary`: latest key financial summary from XBRL facts
- `insider_summary`: aggregated insider-transaction summary
- `market`: latest market-price snapshot
- `recent_news`: latest news headlines
- `data_freshness`: age of each source in days
- `scored_at`: timestamp of the latest composite score used

#### `latest_annual_filing` and `latest_quarterly_filing`

Each filing snapshot can contain:
- `id`
- `accession_number`
- `form_type`
- `filed_at`
- `period_of_report`
- `is_extracted`
- `is_xbrl_parsed`
- `is_embedded`
- `is_signal_scored`
- `processing_status`

This is useful for checking how far a filing has progressed through the
pipeline.

#### `signals`

Each signal row can contain:
- `signal_name`
- `signal_value`
- `status`
- `detail`
- `computed_at`
- `filing_id`
- `form_type`
- `filed_at`

Examples of signal names you may see:
- `rlds`
- `mda_drift`
- `forward_pessimism`
- `fundamental_deterioration`
- `balance_sheet_stress`
- `revenue_growth_deceleration`
- `earnings_quality`
- `numeric_anomaly`
- `insider_signal`
- `market_signal`
- `sentiment_signal`
- `nci_global`
- `composite_filing_risk`

The `detail` field is a flexible diagnostic payload and may include:
- component scores
- confidence
- coverage ratio
- descriptive metadata
- availability reasons when a signal could not be computed

#### `xbrl_summary`

The XBRL summary is a compact financial snapshot built from the latest XBRL
period found for the company.

Possible fields:
- `revenue`
- `net_income`
- `gross_profit`
- `operating_income`
- `total_assets`
- `total_debt`
- `period_end`

This is the endpoint section to use if you want numbers like revenue or net
income without querying raw `xbrl_facts`.

#### `insider_summary`

The insider summary currently includes:
- `total_transactions`
- `opportunistic_sells`
- `total_sell_value`
- `total_buy_value`
- `latest_transaction_date`

This is derived from `insider_transactions`.

#### `market`

The market snapshot currently includes:
- `close_price`
- `volume`
- `price_date`

This is derived from the latest row in `market_prices`.

#### `recent_news`

Each recent news item can contain:
- `headline`
- `source`
- `published_at`
- `sentiment_score`

This is derived from `news_items`.

#### `data_freshness`

The freshness dictionary currently includes:
- `filings_days_old`
- `xbrl_days_old`
- `market_days_old`
- `news_days_old`
- `signals_days_old`

This helps the frontend show whether the displayed information is recent or
stale.

Typical use:
- Company overview page
- Latest company risk snapshot
- Dashboard cards

### `GET /api/v1/score/{ticker}/value/{field_name}`

Purpose:
- Return only one scalar value from the company score snapshot instead of the full payload

Supported `field_name` values:
- `companies.name`
- `companies.ticker`
- `companies.nci_global`
- `filings.filed_at`
- `filings.latest_annual_filed_at`
- `filings.latest_quarterly_filed_at`
- `market_prices.price_close`
- `news_items.sentiment_score`

Example:

```text
/api/v1/score/NKLA/value/companies.name
/api/v1/score/NKLA/value/companies.nci_global
/api/v1/score/NKLA/value/market_prices.price_close
```

### `GET /api/v1/score/{ticker}_get_{field_name}`

Purpose:
- Backward-compatible alias for direct scalar access in the compact style you requested

Example:

```text
/api/v1/score/NKLA_get_companies.name
/api/v1/score/NKLA_get_companies.nci_global
```

### `GET /api/v1/signals/{ticker}`

Purpose:
- Return signal rows for one company
- Useful when you want the raw signal output instead of the aggregated score

Path parameter:
- `ticker`: ticker, full company name, or CIK

Query parameters:
- `signal_name`: optional exact signal-name filter
- `form_type`: optional filing-type filter such as `10-K` or `10-Q`
- `limit`: max rows to return, default `50`, max `500`

Each row contains:
- `signal_name`
- `signal_value`
- `status`
- `detail`
- `computed_at`
- `filing_id`
- `form_type`
- `filed_at`

Typical use:
- Debugging specific signals
- Reviewing one signal across filings
- Exploring low-level model output

Example:

```text
/api/v1/signals/NKLA?signal_name=nci_global
/api/v1/signals/NKLA?form_type=10-Q&limit=20
```

### `GET /api/v1/signals/{ticker}/history`

Purpose:
- Return the company time series for the composite signal history
- Good for charts

Path parameter:
- `ticker`: ticker, full company name, or CIK

Query parameters:
- `limit`: max history points, default `200`, max `1000`

Current behavior:
- This endpoint reads the `composite_filing_risk` signal rows
- Since `composite_filing_risk` is the alias of `nci_global`, this is
  effectively the company NCI history by filing anchor

Each history point contains:
- `filing_id`
- `accession_number`
- `form_type`
- `filed_at`
- `period_of_report`
- `signal_value`
- `computed_at`

Chart guidance:
- Y-axis: `signal_value`
- X-axis: usually `filed_at`
- Point label or series split: `form_type`

Typical use:
- NCI chart over time
- Filing-by-filing trend analysis

### `GET /api/v1/filings/{ticker}`

Purpose:
- Return filing rows for one company
- Useful for pipeline inspection and operational debugging

### `GET /api/v1/embeddings/{ticker}`

Purpose:
- Return stored embedding chunks for one company
- Useful when you want access to `embeddings.text` and `embeddings.embedding`

Path parameter:
- `ticker`: ticker, full company name, or CIK

Query parameters:
- `filing_id`: optional filing filter
- `form_type`: optional filing-type filter such as `10-K` or `10-Q`
- `section`: optional filing-section filter such as `risk_factors` or `mda`
- `include_vector`: whether to include the numeric embedding vector, default `true`
- `limit`: max rows to return, default `20`, max `500`

Each row contains:
- `id`
- `filing_id`
- `filing_section_id`
- `accession_number`
- `form_type`
- `filed_at`
- `section`
- `chunk_idx`
- `text`
- `embedding`
- `provider`
- `embedding_model`
- `reconstruction_error`
- `anomaly_score`
- `created_at`

Typical use:
- Inspecting chunk text that was embedded
- Exporting vectors for downstream retrieval or debugging
- Verifying which filing sections produced stored embeddings

Example:

```text
/api/v1/embeddings/NKLA?limit=10
/api/v1/embeddings/AAPL?form_type=10-K&section=risk_factors&include_vector=true&limit=5
```

### `GET /api/v1/embeddings/{ticker}/latest`

Purpose:
- Return embeddings for only the most recent filing that already has stored embeddings
- Useful when the client wants the latest chunk text and vectors without first looking up a filing id

Path parameter:
- `ticker`: ticker, full company name, or CIK

Query parameters:
- `form_type`: optional filing-type filter such as `10-K` or `10-Q`
- `section`: optional filing-section filter such as `risk_factors` or `mda`
- `include_vector`: whether to include the numeric embedding vector, default `true`
- `limit`: max rows to return, default `20`, max `500`

Behavior:
- Finds the latest filing for the company that already has embedding rows
- Returns only the embedding rows from that filing

Example:

```text
/api/v1/embeddings/NKLA/latest?limit=10
/api/v1/embeddings/AAPL/latest?form_type=10-K&section=mda&include_vector=false&limit=5
```

### `GET /api/v1/embeddings/{ticker}/latest/value/{field_name}`

Purpose:
- Return only one scalar value from the first matching embedding row of the latest embedded filing

Supported `field_name` values:
- `embeddings.text`
- `embeddings.embedding`
- `filings.filed_at`

Useful query parameters:
- `section`
- `form_type`
- `chunk_idx`
- `include_vector`

Example:

```text
/api/v1/embeddings/NKLA/latest/value/embeddings.text
/api/v1/embeddings/NKLA/latest/value/embeddings.embedding?chunk_idx=0
/api/v1/embeddings/NKLA/latest/value/filings.filed_at
```

### `GET /api/v1/embeddings/{ticker}/latest_get_{field_name}`

Purpose:
- Alias route for compact scalar access on the latest embeddings endpoint

Example:

```text
/api/v1/embeddings/NKLA/latest_get_embeddings.text
/api/v1/embeddings/NKLA/latest_get_embeddings.embedding?chunk_idx=0
```

Path parameter:
- `ticker`

Query parameters:
- `form_type`: optional filter like `10-K`, `10-Q`, `4`
- `limit`: max rows to return, default `10`, max `200`

Each filing snapshot contains:
- `id`
- `accession_number`
- `form_type`
- `filed_at`
- `period_of_report`
- `is_extracted`
- `is_xbrl_parsed`
- `is_embedded`
- `is_signal_scored`
- `processing_status`

Typical use:
- Check whether a company filing was fully processed
- See which filings exist for a company
- Debug missing signals or missing XBRL/embedding stages

## Error Behavior

Common cases:
- `404`: ticker not found in the `companies` table
- `422`: invalid query parameter value
- `503`: health endpoint could not reach the database
- `500`: unexpected internal API error

For ticker-related endpoints, if a company does not exist yet, the API tells
you to ingest that company first.

## How The API Maps To Stored Data

At a high level:
- `companies` provides the company identity
- `filings` provides filing metadata and pipeline flags
- `signal_scores` provides named low-level and composite signals
- `nci_scores` stores the structured NCI layer output used elsewhere in the
  system
- `xbrl_facts` powers the financial summary
- `insider_transactions` powers insider summaries and behavior signals
- `market_prices` powers market snapshots and market signals
- `news_items` powers recent news and sentiment signals

## Recommended Frontend Usage

Use these routes as the default building blocks:
- Company identity list: `GET /api/v1/companies`
- Company ticker list: `GET /api/v1/companies/tickers`
- Company name to ticker lookup: `GET /api/v1/companies/ticker-by-name?name=...`
- Run a company backfill: `POST /api/v1/pipelines/backfill/company`
- Run company signals: `POST /api/v1/pipelines/signals/company`
- Run one filing signal job: `POST /api/v1/pipelines/signals/filing/{filing_id}`
- Poll a pipeline job: `GET /api/v1/pipelines/jobs/{job_id}`
- Overview page: `GET /api/v1/score/{ticker}`
- Scalar overview fields: `GET /api/v1/score/{ticker}/value/{field_name}`
- Signal explorer: `GET /api/v1/signals/{ticker}`
- NCI chart: `GET /api/v1/signals/{ticker}/history`
- Filing debug page: `GET /api/v1/filings/{ticker}`
- Embedding explorer: `GET /api/v1/embeddings/{ticker}`
- Latest embedding explorer: `GET /api/v1/embeddings/{ticker}/latest`
- Latest embedding scalar fields: `GET /api/v1/embeddings/{ticker}/latest/value/{field_name}`
- Health monitoring: `GET /health`
