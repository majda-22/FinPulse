"""
run_signal_validation.py

Compatibility wrapper for the signal validation report utility.
The package-native implementation lives in `signals.validation_report`.
"""

from signals import validation_report as _impl

generate_signal_validation_report = _impl.generate_signal_validation_report
main = _impl.main


if __name__ == "__main__":
    main()
