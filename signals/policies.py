from __future__ import annotations


POSITIVE_OUTLOOK_ANCHOR = (
    "The company delivered strong revenue growth and improved profitability."
)
OPTIMISTIC_FORWARD_ANCHOR = (
    "strong growth outlook, confident in results, expect continued improvement"
)
PESSIMISTIC_FORWARD_ANCHOR = (
    "face significant headwinds, uncertain environment, challenges ahead, cannot guarantee"
)
FORWARD_LOOKING_KEYWORDS = (
    "expect",
    "expects",
    "expecting",
    "outlook",
    "guidance",
    "forecast",
    "anticipate",
    "anticipates",
    "believe",
    "believes",
    "will",
    "would",
    "could",
    "may",
    "plan",
    "plans",
    "continue",
    "continuing",
    "headwind",
    "headwinds",
    "uncertain",
    "challenge",
    "challenges",
)

TEXT_COMPONENT_WEIGHTS = {
    "tfidf_drift": 0.40,
    "semantic_novelty": 0.60,
}
TEXT_CONFIDENCE_CHUNK_TARGET = 8

FUNDAMENTAL_MARGIN_WEIGHTS = {
    "gross_margin": 0.35,
    "operating_margin": 0.40,
    "net_margin": 0.25,
}
BALANCE_SHEET_STRESS_WEIGHTS = {
    "leverage_score": 0.35,
    "cash_score": 0.30,
    "cf_quality_score": 0.35,
}
NUMERIC_HISTORY_TARGET = 4

ROUTINE_TRANSACTION_CODES = {"A", "F", "M"}
SENIOR_ROLES = {"CEO", "CFO", "President", "CTO", "Director"}
SENIOR_OPPORTUNISTIC_ROLES = {"CEO", "CFO", "President", "Director"}
ROLE_WEIGHTS = {
    "CEO": 1.00,
    "CFO": 0.90,
    "President": 0.85,
    "COO": 0.80,
    "Director": 0.60,
    "Other Officer": 0.50,
}
BEHAVIOR_ACTIVE_INSIDER_TARGET = 3
FORM4_GOVERNANCE_PENALTY_CAP = 0.30
FORM4_GOVERNANCE_PENALTY_MULTIPLIER = 0.50

CONVERGENCE_THRESHOLDS = {
    "text": 0.55,
    "numeric": 0.55,
    "behavior": 0.50,
    "market": 0.50,
    "sentiment": 0.50,
}
CONVERGENCE_TIERS = {
    5: ("full", 0.20),
    4: ("strong", 0.15),
    3: ("moderate", 0.10),
}

NCI_WEIGHTS = {
    "rlds": 0.20,
    "mda_drift": 0.08,
    "forward_pessimism": 0.07,
    "fundamental_deterioration": 0.18,
    "balance_sheet_stress": 0.07,
    "revenue_growth_deceleration": 0.05,
    "earnings_quality": 0.05,
    "numeric_anomaly": 0.05,
    "insider_signal": 0.10,
    "market_signal": 0.10,
    "sentiment_signal": 0.10,
}

MARKET_SIGNAL_WEIGHTS = {
    "price_momentum_risk": 0.40,
    "volatility_spike": 0.35,
    "market_fundamental_divergence": 0.25,
}

SENTIMENT_SIGNAL_WEIGHTS = {
    "news_sentiment_signal": 0.70,
    "news_volume_spike": 0.30,
}

NCI_COVERAGE_HIGH = 0.80
NCI_COVERAGE_MEDIUM = 0.60
