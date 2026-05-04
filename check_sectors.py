# check_sectors.py
from app.db.session import SessionLocal
from app.db.models import Company

session = SessionLocal()

companies = session.query(
    Company.sic_code, 
    Company.sic_description, 
    Company.sector
).distinct().order_by(Company.sic_code).all()

print(f"Total secteurs: {len(companies)}\n")
for c in companies:
    print(f"SIC: {c.sic_code} | Description: {c.sic_description} | Secteur: {c.sector}")

session.close()