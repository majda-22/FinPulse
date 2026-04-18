from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SignalDefinition:
    name: str
    layer: str
    description: str


SIGNAL_DEFINITIONS: dict[str, SignalDefinition] = {
    "rlds": SignalDefinition(
        name="rlds",
        layer="text",
        description="Risk Lexical Drift Score measuring how much Risk Factors changed versus the prior comparable filing.",
    ),
    "mda_drift": SignalDefinition(
        name="mda_drift",
        layer="text",
        description="Management Discussion & Analysis drift measuring vocabulary and semantic change versus the prior comparable filing.",
    ),
    "forward_pessimism": SignalDefinition(
        name="forward_pessimism",
        layer="text",
        description="Measures whether forward-looking MDA language has shifted toward pessimistic framing versus optimistic framing.",
    ),
    "text_sentiment": SignalDefinition(
        name="text_sentiment",
        layer="text",
        description="Auxiliary positive-outlook similarity score derived from current MDA language.",
    ),
    "narrative_numeric_divergence": SignalDefinition(
        name="narrative_numeric_divergence",
        layer="composite",
        description="Diagnostic gap between management optimism in text and underlying numeric health.",
    ),
    "fundamental_deterioration": SignalDefinition(
        name="fundamental_deterioration",
        layer="numbers",
        description="Composite deterioration score from gross, operating, and net margin declines.",
    ),
    "revenue_growth_deceleration": SignalDefinition(
        name="revenue_growth_deceleration",
        layer="numbers",
        description="Measures how much revenue growth slowed relative to the prior comparable period.",
    ),
    "balance_sheet_stress": SignalDefinition(
        name="balance_sheet_stress",
        layer="numbers",
        description="Measures leverage increase, cash deterioration, and weak earnings-to-cash conversion.",
    ),
    "earnings_quality": SignalDefinition(
        name="earnings_quality",
        layer="numbers",
        description="Accrual-based warning score for whether reported earnings are backed by cash.",
    ),
    "numeric_anomaly": SignalDefinition(
        name="numeric_anomaly",
        layer="numbers",
        description="Normalized z-score distance between the current financial profile and the company’s own history.",
    ),
    "ita": SignalDefinition(
        name="ita",
        layer="behavior",
        description="Insider Transaction Asymmetry score measuring opportunistic insider selling pressure around a filing.",
    ),
    "insider_concentration": SignalDefinition(
        name="insider_concentration",
        layer="behavior",
        description="Measures whether opportunistic selling is concentrated across multiple insiders at the same time.",
    ),
    "insider_signal": SignalDefinition(
        name="insider_signal",
        layer="behavior",
        description="Combined insider behavior score built from ITA, seller concentration, and late Form 4 governance penalty.",
    ),
    "price_momentum_risk": SignalDefinition(
        name="price_momentum_risk",
        layer="market",
        description="Weighted downside momentum score across 1, 3, 6, and 12 month price windows.",
    ),
    "volatility_spike": SignalDefinition(
        name="volatility_spike",
        layer="market",
        description="Measures whether recent realized volatility is elevated versus the company’s own longer-run baseline.",
    ),
    "market_fundamental_divergence": SignalDefinition(
        name="market_fundamental_divergence",
        layer="market",
        description="Optional overvaluation score comparing the company’s implied P/E to sector peers in the local database.",
    ),
    "market_signal": SignalDefinition(
        name="market_signal",
        layer="market",
        description="Combined market-implied risk signal built from downside momentum, volatility, and sector-relative valuation stretch.",
    ),
    "news_sentiment_signal": SignalDefinition(
        name="news_sentiment_signal",
        layer="sentiment",
        description="Combines 30-day weighted news sentiment and recent sentiment deterioration versus the trailing 90-day baseline.",
    ),
    "news_volume_spike": SignalDefinition(
        name="news_volume_spike",
        layer="sentiment",
        description="Measures whether recent news flow is running materially above the company’s normal volume.",
    ),
    "sentiment_signal": SignalDefinition(
        name="sentiment_signal",
        layer="sentiment",
        description="Combined external narrative risk signal built from weighted news tone and abnormal news volume.",
    ),
    "convergence_signal": SignalDefinition(
        name="convergence_signal",
        layer="composite",
        description="Tiered multi-layer convergence signal showing how many of the five evidence layers are simultaneously elevated.",
    ),
    "nci_global": SignalDefinition(
        name="nci_global",
        layer="composite",
        description="FinPulse v2 composite risk score built from text, numeric, behavioral, market, and sentiment evidence plus convergence.",
    ),
    "composite_filing_risk": SignalDefinition(
        name="composite_filing_risk",
        layer="composite",
        description="Backward-compatible alias for nci_global.",
    ),
}


def get_signal_definition(signal_name: str) -> SignalDefinition | None:
    return SIGNAL_DEFINITIONS.get(signal_name)
