"""
run_backfill_company.py

Compatibility wrapper for the full company backfill pipeline.
The package-native implementation now lives in `pipelines.run_backfill_company`.
"""

from pipelines import run_backfill_company as _impl

run_backfill_company = _impl.run_backfill_company
main = _impl.main


if __name__ == "__main__":
    main()
