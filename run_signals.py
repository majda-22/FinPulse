"""
run_signals.py

Compatibility wrapper for the filing signals pipeline.
The package-native implementation now lives in `pipelines.signals_pipeline`.
"""

from pipelines import signals_pipeline as _impl

run_all_signals = _impl.run_all_signals
SignalPipelineError = _impl.SignalPipelineError
main = _impl.main


if __name__ == "__main__":
    args = _impl._parse_args()
    main(args.filing_id)
