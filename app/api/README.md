# FinPulse API

This folder contains the read-only HTTP API for FinPulse.

The API does not compute new scores on demand. It reads data already written by
the ingestion, processing, and signal pipelines from the database.

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
- `ticker`: company ticker, for example `AAPL`, `TSLA`, `NKLA`

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

### `GET /api/v1/signals/{ticker}`

Purpose:
- Return signal rows for one company
- Useful when you want the raw signal output instead of the aggregated score

Path parameter:
- `ticker`

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
- `ticker`

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
- `ticker`

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
- `ticker`

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
- Overview page: `GET /api/v1/score/{ticker}`
- Signal explorer: `GET /api/v1/signals/{ticker}`
- NCI chart: `GET /api/v1/signals/{ticker}/history`
- Filing debug page: `GET /api/v1/filings/{ticker}`
- Embedding explorer: `GET /api/v1/embeddings/{ticker}`
- Latest embedding explorer: `GET /api/v1/embeddings/{ticker}/latest`
- Health monitoring: `GET /health`
