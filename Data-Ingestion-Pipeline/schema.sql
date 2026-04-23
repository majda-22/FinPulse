-- ============================================================================
-- FinPulse live schema snapshot
-- Generated from the current PostgreSQL database on 2026-04-18.
-- Source of truth: live DB / Alembic migrations / SQLAlchemy models.
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "vector";

-- ----------------------------------------------------------------------------
-- Table: companies
-- ----------------------------------------------------------------------------
CREATE TABLE "companies" (
    "id" integer DEFAULT nextval('companies_id_seq'::regclass) NOT NULL,
    "cik" character varying NOT NULL,
    "ticker" character varying NOT NULL,
    "name" character varying NOT NULL,
    "sic_code" character varying,
    "sic_description" character varying,
    "sector" character varying,
    "exchange" character varying,
    "is_active" boolean NOT NULL,
    "first_filing_at" date,
    "last_filing_at" date,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "companies_pkey" PRIMARY KEY (id),
    CONSTRAINT "companies_cik_key" UNIQUE (cik),
    CONSTRAINT "companies_ticker_key" UNIQUE (ticker)
);

-- ----------------------------------------------------------------------------
-- Table: filings
-- ----------------------------------------------------------------------------
CREATE TABLE "filings" (
    "id" integer DEFAULT nextval('filings_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "accession_number" text NOT NULL,
    "form_type" character varying NOT NULL,
    "filed_at" date NOT NULL,
    "period_of_report" date,
    "fiscal_year" integer,
    "fiscal_quarter" smallint,
    "raw_s3_key" text NOT NULL,
    "raw_size_bytes" integer,
    "is_extracted" boolean NOT NULL,
    "is_xbrl_parsed" boolean NOT NULL,
    "is_embedded" boolean NOT NULL,
    "is_signal_scored" boolean NOT NULL,
    "is_anomaly_scored" boolean NOT NULL,
    "processing_status" character varying NOT NULL,
    "last_error_message" text,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "is_text_signal_scored" boolean NOT NULL,
    "is_numeric_signal_scored" boolean NOT NULL,
    "is_composite_signal_scored" boolean NOT NULL,
    "is_insider_signal_scored" boolean NOT NULL,
    "is_form4_parsed" boolean NOT NULL,
    CONSTRAINT "filings_pkey" PRIMARY KEY (id),
    CONSTRAINT "filings_accession_number_key" UNIQUE (accession_number),
    CONSTRAINT "filings_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- Table: filing_sections
-- ----------------------------------------------------------------------------
CREATE TABLE "filing_sections" (
    "id" integer DEFAULT nextval('filing_sections_id_seq'::regclass) NOT NULL,
    "filing_id" integer NOT NULL,
    "company_id" integer NOT NULL,
    "section" character varying NOT NULL,
    "sequence_idx" smallint NOT NULL,
    "text" text NOT NULL,
    "s3_key" text,
    "extractor_version" character varying,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "filing_sections_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_filing_sections_filing_section_seq" UNIQUE (filing_id, section, sequence_idx),
    CONSTRAINT "filing_sections_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id),
    CONSTRAINT "filing_sections_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- Table: xbrl_facts
-- ----------------------------------------------------------------------------
CREATE TABLE "xbrl_facts" (
    "id" integer DEFAULT nextval('xbrl_facts_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "filing_id" integer,
    "taxonomy" character varying NOT NULL,
    "concept" character varying NOT NULL,
    "label" text,
    "value" numeric,
    "unit" character varying,
    "decimals" character varying,
    "period_type" character varying,
    "period_start" date,
    "period_end" date NOT NULL,
    "fiscal_year" integer,
    "fiscal_quarter" smallint,
    "form_type" character varying,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "xbrl_facts_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_xbrl_fact_business_key" UNIQUE (company_id, taxonomy, concept, period_type, period_start, period_end, unit, form_type),
    CONSTRAINT "xbrl_facts_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT "xbrl_facts_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE SET NULL
);

-- ----------------------------------------------------------------------------
-- Table: guidance_statements
-- ----------------------------------------------------------------------------
CREATE TABLE "guidance_statements" (
    "id" integer DEFAULT nextval('guidance_statements_id_seq'::regclass) NOT NULL,
    "filing_id" integer NOT NULL,
    "company_id" integer NOT NULL,
    "raw_text" text NOT NULL,
    "metric" character varying,
    "guided_point" numeric,
    "unit" character varying,
    "period_type" character varying,
    "guidance_period_end" date,
    "extractor_version" character varying,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "guidance_statements_pkey" PRIMARY KEY (id),
    CONSTRAINT "guidance_statements_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id),
    CONSTRAINT "guidance_statements_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- Table: embeddings
-- ----------------------------------------------------------------------------
CREATE TABLE "embeddings" (
    "id" bigint DEFAULT nextval('embeddings_id_seq'::regclass) NOT NULL,
    "filing_section_id" integer NOT NULL,
    "company_id" integer NOT NULL,
    "filing_id" integer NOT NULL,
    "chunk_idx" integer NOT NULL,
    "text" text NOT NULL,
    "embedding" vector(1024) NOT NULL,
    "provider" character varying NOT NULL,
    "embedding_model" character varying NOT NULL,
    "reconstruction_error" double precision,
    "anomaly_score" double precision,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "embeddings_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_embeddings_section_chunk" UNIQUE (filing_section_id, chunk_idx),
    CONSTRAINT "embeddings_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id),
    CONSTRAINT "embeddings_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE CASCADE,
    CONSTRAINT "embeddings_filing_section_id_fkey" FOREIGN KEY (filing_section_id) REFERENCES filing_sections(id) ON DELETE CASCADE
);

CREATE INDEX idx_embeddings_company ON public.embeddings USING btree (company_id);
CREATE INDEX idx_embeddings_filing ON public.embeddings USING btree (filing_id);
CREATE INDEX idx_embeddings_filing_section ON public.embeddings USING btree (filing_section_id);
CREATE INDEX idx_embeddings_reconstruction ON public.embeddings USING btree (reconstruction_error);

-- ----------------------------------------------------------------------------
-- Table: insider_transactions
-- ----------------------------------------------------------------------------
CREATE TABLE "insider_transactions" (
    "id" integer DEFAULT nextval('insider_transactions_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "filing_id" integer,
    "insider_name" text NOT NULL,
    "transaction_date" date NOT NULL,
    "transaction_code" character varying NOT NULL,
    "shares" numeric NOT NULL,
    "price_per_share" numeric,
    "transaction_value" numeric,
    "is_derivative" boolean NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "transaction_uid" text NOT NULL,
    "accession_number" text NOT NULL,
    "cik" character varying NOT NULL,
    "ticker" character varying,
    "issuer_name" text,
    "insider_cik" character varying,
    "is_director" boolean NOT NULL,
    "is_officer" boolean NOT NULL,
    "is_ten_percent_owner" boolean NOT NULL,
    "is_other" boolean NOT NULL,
    "officer_title" text,
    "transaction_type_normalized" character varying NOT NULL,
    "shares_owned_after" numeric,
    "ownership_nature" character varying,
    "acquired_disposed_code" character varying,
    "form_type" character varying NOT NULL,
    "filed_at" date,
    "source_url" text,
    "raw_detail" jsonb,
    "security_title" text DEFAULT ''::text NOT NULL,
    CONSTRAINT "insider_transactions_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_insider_transaction_dedup" UNIQUE (accession_number, insider_name, transaction_date, transaction_code, shares, price_per_share, security_title, ownership_nature, acquired_disposed_code, is_derivative),
    CONSTRAINT "uq_insider_transaction_uid" UNIQUE (transaction_uid),
    CONSTRAINT "insider_transactions_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT "insider_transactions_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE CASCADE
);

CREATE INDEX idx_insider_company_type ON public.insider_transactions USING btree (company_id, transaction_type_normalized, transaction_date);

-- ----------------------------------------------------------------------------
-- Table: signal_scores
-- ----------------------------------------------------------------------------
CREATE TABLE "signal_scores" (
    "id" integer DEFAULT nextval('signal_scores_id_seq'::regclass) NOT NULL,
    "filing_id" integer NOT NULL,
    "company_id" integer NOT NULL,
    "rlds" double precision,
    "gce" double precision,
    "ita" double precision,
    "convergence" boolean NOT NULL,
    "convergence_reason" text,
    "model_version" character varying,
    "computed_at" timestamp with time zone DEFAULT now() NOT NULL,
    "signal_name" character varying,
    "signal_value" double precision,
    "detail" jsonb,
    CONSTRAINT "signal_scores_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_signal_scores_filing_signal_name" UNIQUE (filing_id, signal_name),
    CONSTRAINT "signal_scores_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id),
    CONSTRAINT "signal_scores_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE CASCADE
);

CREATE INDEX idx_signal_company_name ON public.signal_scores USING btree (company_id, signal_name, computed_at);
CREATE INDEX idx_signal_name ON public.signal_scores USING btree (signal_name);

-- ----------------------------------------------------------------------------
-- Table: pipeline_events
-- ----------------------------------------------------------------------------
CREATE TABLE "pipeline_events" (
    "id" bigint DEFAULT nextval('pipeline_events_id_seq'::regclass) NOT NULL,
    "filing_id" integer,
    "company_id" integer,
    "event_type" text NOT NULL,
    "layer" text NOT NULL,
    "duration_ms" integer,
    "detail" jsonb,
    "occurred_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "pipeline_events_pkey" PRIMARY KEY (id),
    CONSTRAINT "pipeline_events_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    CONSTRAINT "pipeline_events_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE SET NULL
);

-- ----------------------------------------------------------------------------
-- Table: nci_scores
-- ----------------------------------------------------------------------------
CREATE TABLE "nci_scores" (
    "id" integer DEFAULT nextval('nci_scores_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "filing_id" integer,
    "signal_score_id" integer,
    "nci_global" double precision NOT NULL,
    "nci_lower" double precision,
    "nci_upper" double precision,
    "data_fresh" boolean NOT NULL,
    "staleness_reason" text,
    "model_version" character varying,
    "top_anomalous_paragraphs" json,
    "computed_at" timestamp with time zone DEFAULT now() NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "text_source_filing" integer,
    "xbrl_source_filing" integer,
    "event_type" character varying NOT NULL,
    "fiscal_year" integer,
    "fiscal_quarter" integer,
    "convergence_tier" character varying,
    "layers_elevated" integer,
    "confidence" character varying,
    "coverage_ratio" double precision,
    "text_staleness_days" integer,
    "signal_text" double precision,
    "signal_mda" double precision,
    "signal_pessimism" double precision,
    "signal_fundamental" double precision,
    "signal_balance" double precision,
    "signal_growth" double precision,
    "signal_earnings" double precision,
    "signal_anomaly" double precision,
    "signal_insider" double precision,
    "signal_market" double precision,
    "signal_sentiment" double precision,
    CONSTRAINT "nci_scores_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_nci_company_computed_at" UNIQUE (company_id, computed_at),
    CONSTRAINT "fk_nci_scores_text_source_filing" FOREIGN KEY (text_source_filing) REFERENCES filings(id) ON DELETE SET NULL,
    CONSTRAINT "fk_nci_scores_xbrl_source_filing" FOREIGN KEY (xbrl_source_filing) REFERENCES filings(id) ON DELETE SET NULL,
    CONSTRAINT "nci_scores_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT "nci_scores_filing_id_fkey" FOREIGN KEY (filing_id) REFERENCES filings(id) ON DELETE SET NULL,
    CONSTRAINT "nci_scores_signal_score_id_fkey" FOREIGN KEY (signal_score_id) REFERENCES signal_scores(id) ON DELETE SET NULL
);

-- ----------------------------------------------------------------------------
-- Table: news_items
-- ----------------------------------------------------------------------------
CREATE TABLE "news_items" (
    "id" integer DEFAULT nextval('news_items_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "ticker" character varying NOT NULL,
    "source_name" character varying NOT NULL,
    "publisher" character varying,
    "headline" text NOT NULL,
    "summary" text,
    "url" text NOT NULL,
    "published_at" timestamp with time zone NOT NULL,
    "retrieved_at" timestamp with time zone DEFAULT now() NOT NULL,
    "dedupe_hash" character varying(64) NOT NULL,
    "sentiment_label" character varying,
    "raw_json" jsonb,
    CONSTRAINT "news_items_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_news_items_company_dedupe_hash" UNIQUE (company_id, dedupe_hash),
    CONSTRAINT "news_items_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE INDEX idx_news_items_company_published_at ON public.news_items USING btree (company_id, published_at);
CREATE INDEX idx_news_items_ticker_published_at ON public.news_items USING btree (ticker, published_at);

-- ----------------------------------------------------------------------------
-- Table: market_prices
-- ----------------------------------------------------------------------------
CREATE TABLE "market_prices" (
    "id" integer DEFAULT nextval('market_prices_id_seq'::regclass) NOT NULL,
    "company_id" integer NOT NULL,
    "ticker" character varying NOT NULL,
    "trading_date" date NOT NULL,
    "open" numeric(18,6),
    "high" numeric(18,6),
    "low" numeric(18,6),
    "close" numeric(18,6),
    "adjusted_close" numeric(18,6),
    "volume" bigint,
    "provider" character varying NOT NULL,
    "retrieved_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "market_prices_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_market_prices_company_date_provider" UNIQUE (company_id, trading_date, provider),
    CONSTRAINT "market_prices_company_id_fkey" FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE INDEX idx_market_prices_company_trading_date ON public.market_prices USING btree (company_id, trading_date);
CREATE INDEX idx_market_prices_ticker_trading_date ON public.market_prices USING btree (ticker, trading_date);

-- ----------------------------------------------------------------------------
-- Table: macro_observations
-- ----------------------------------------------------------------------------
CREATE TABLE "macro_observations" (
    "id" integer DEFAULT nextval('macro_observations_id_seq'::regclass) NOT NULL,
    "series_id" character varying NOT NULL,
    "observation_date" date NOT NULL,
    "value" numeric(18,6),
    "provider" character varying NOT NULL,
    "retrieved_at" timestamp with time zone DEFAULT now() NOT NULL,
    "frequency" character varying,
    "units" character varying,
    "title" text,
    CONSTRAINT "macro_observations_pkey" PRIMARY KEY (id),
    CONSTRAINT "uq_macro_observations_series_date_provider" UNIQUE (series_id, observation_date, provider)
);

CREATE INDEX idx_macro_observations_series_date ON public.macro_observations USING btree (series_id, observation_date);

-- ----------------------------------------------------------------------------
-- Table: alembic_version
-- ----------------------------------------------------------------------------
CREATE TABLE "alembic_version" (
    "version_num" character varying(32) NOT NULL,
    CONSTRAINT "alembic_version_pkc" PRIMARY KEY (version_num)
);

-- ----------------------------------------------------------------------------
-- Installed extensions present in the live database
-- ----------------------------------------------------------------------------
-- vector

-- ----------------------------------------------------------------------------
-- Objects not present in the live database
-- ----------------------------------------------------------------------------
-- No custom enums in public schema
-- No views in public schema
-- No user-defined triggers in public schema
-- No FinPulse helper SQL functions in public schema

