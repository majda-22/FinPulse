# Signals

FinPulse now uses five evidence layers plus one composite layer:

- `text_signals.py`: what management says and how that language shifts
- `numeric_signals.py`: what the financials show
- `behavior_signals.py`: what insiders do
- `market_signals.py`: what the market is pricing in
- `sentiment_signals.py`: what external coverage is saying
- `composite_engine.py`: how all five layers converge into `nci_global`
- `catalog.py`: canonical signal names, layers, and plain-English descriptions

Primary text signals:

- `rlds`: Risk Lexical Drift Score for the Risk Factors section
- `mda_drift`: drift score for Management Discussion & Analysis
- `forward_pessimism`: forward-looking MDA tone shifting toward caution or pessimism
- `text_sentiment`: auxiliary positive-outlook similarity score used for diagnostics and insider amplification

Primary numeric signals:

- `fundamental_deterioration`: margin-compression risk score
- `revenue_growth_deceleration`: slowing-growth risk score
- `balance_sheet_stress`: leverage, cash, and cash-conversion stress score
- `earnings_quality`: accrual-based earnings-quality warning score
- `numeric_anomaly`: distance from the company’s own numeric history

Primary behavior signals:

- `ita`: Insider Transaction Asymmetry around a filing window
- `insider_concentration`: whether opportunistic selling is spread across multiple insiders
- `insider_signal`: combined behavioral risk signal from `ita`, concentration, and late Form 4 governance penalty

Primary market signals:

- `price_momentum_risk`: weighted downside momentum across 1, 3, 6, and 12 month windows
- `volatility_spike`: realized-volatility ratio versus the company’s own baseline
- `market_fundamental_divergence`: optional overvaluation stretch versus local sector peers
- `market_signal`: combined market-implied risk signal

Primary sentiment signals:

- `news_sentiment_signal`: recency-weighted news tone plus recent deterioration
- `news_volume_spike`: abnormal recent article volume
- `sentiment_signal`: combined external narrative risk signal

Composite outputs:

- `narrative_numeric_divergence`: diagnostic gap between management optimism and numeric health
- `convergence_signal`: tiered multi-layer convergence boost based on how many layers are elevated
- `nci_global`: final FinPulse v2 composite score
- `composite_filing_risk`: backward-compatible alias for `nci_global`

Compatibility shims remain in the legacy files (`section_signals.py`, `xbrl_signals.py`, `insider_signals.py`, `composite_signals.py`) so existing pipelines can keep importing them while the internal formulas live in the cleaner layer modules above.

Implementation notes:

- Text comparisons are section-aware: quarterly Risk Factors compare to the latest annual baseline, while quarterly MDA compares to the prior quarter.
- Numeric signals annualize quarterly duration facts before comparing them with annual filings.
- Behavioral signals now include a governance penalty for late Form 4 filing behavior.
- Market and sentiment layers are stored as named signal rows per anchor filing so the composite layer only fuses existing evidence.
- `nci_scores` stores the per-layer values, convergence tier, coverage ratio, confidence label, and source filing references used for each anchor computation.
