from app.db.session import SessionLocal
from app.db.models.company import Company


def main():
    db = SessionLocal()
    try:
        existing = db.query(Company).filter(Company.cik == "0000320193").first()

        if existing:
            print(f"Company already exists: {existing.ticker} - {existing.name}")
            return

        company = Company(
            cik="0000320193",
            ticker="AAPL",
            name="Apple Inc.",
            sic_code="3571",
            sector="tech",
            exchange="NASDAQ",
            is_active=True,
        )
        db.add(company)
        db.commit()
        print("Company inserted successfully")

    except Exception as e:
        db.rollback()
        print("Error:", e)

    finally:
        db.close()


if __name__ == "__main__":
    main()