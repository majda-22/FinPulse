"""
run_form4_pipeline.py

Compatibility wrapper for the Form 4 pipeline.
The package-native implementation now lives in `pipelines.form4_pipeline`.
"""

from pipelines import form4_pipeline as _impl

run_form4_pipeline = _impl.run_form4_pipeline
parse_pending_form4_filings = _impl.parse_pending_form4_filings
parse_pending_form4_filings_async = _impl.parse_pending_form4_filings_async
main = _impl.main


if __name__ == "__main__":
    main()
