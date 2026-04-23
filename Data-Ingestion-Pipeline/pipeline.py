"""
pipeline.py

Compatibility wrapper for the raw filing ingestion pipeline.
The package-native implementation now lives in `pipelines.ingestion_pipeline`.
"""

from pipelines import ingestion_pipeline as _impl

ingest_company = _impl.ingest_company
ingest_ticker = _impl.ingest_ticker
ingest_batch = _impl.ingest_batch
main = _impl.main
_download_filing_text = _impl._download_filing_text


if __name__ == "__main__":
    main()
