from app.db.session import SessionLocal
from signals.composite_engine import compute_composite_signals
from app.db.models import Filing

session = SessionLocal()

filing = session.query(Filing).filter(
    Filing.is_signal_scored == True
).order_by(Filing.filed_at.desc()).first()

if not filing:
    print("Aucun filing trouvé !")
else:
    print(f"Testing on filing {filing.id} ({filing.company.name})...")
    results = compute_composite_signals(session, filing_id=filing.id)

    for signal in results:
        name = signal["signal_name"]
        value = signal["signal_value"]
        print(f"  {name}: {value}")

        if name == "triplet_convergence_signal":
            detail = signal["detail"]
            print(f'    Signals elevated: {detail["triplet_signals_elevated"]}/3')
            print(f'    Confidence: {detail["triplet_confidence"]}')
            print(f'    Boost: {detail["triplet_boost"]}')

session.close()