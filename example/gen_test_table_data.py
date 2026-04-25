"""

- A starter script for creating and populating `products`
  table with some dummy data.

"""

import random
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float
from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
#   CONFIGURATION - CHANGE THESE VALUES
# ──────────────────────────────────────────────────────────────────────────────
# Assumed the postres service points to port 5433 on the host
DATABASE_URL = "postgresql+psycopg2://test_user:test_pwd@localhost:5433/ai_bi_db"
# ──────────────────────────────────────────────────────────────────────────────

fake = Faker()

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    category = Column(String(255))
    revenue = Column(Float)


def create_table(engine):
    print("Creating tables...........")
    # Create table only if it doesn't exist
    Base.metadata.create_all(engine)
    print("Table 'products' checked / created.")


def clear_table_if_exists(session):
    # Optional: clean previous data (comment out if you want to append)
    session.execute(text("DELETE FROM products"))
    session.commit()
    print("Previous records removed (if any).")


def generate_products(n=1000):
    print("Generating products.......")
    categories = [
        "Smartphones", "Laptops", "Headphones", "Tablets", "Smart Watches",
        "Monitors", "Keyboards", "Mice", "Speakers", "Cameras",
        "External SSD", "Power Banks", "Chargers", "Cables", "Memory Cards",
        "Gaming Consoles", "Drones", "Action Cameras", "Earbuds", "Fitness Trackers"
    ]

    brands = ["Apple", "Samsung", "Sony", "Dell", "HP", "Lenovo", "Asus", "Xiaomi",
              "Anker", "Logitech", "JBL", "Bose", "Canon", "Nikon", "GoPro", "DJI"]

    products = []

    for _ in range(n):
        brand = random.choice(brands)
        category = random.choice(categories)

        # Generate more realistic names depending on category
        if category == "Smartphones":
            name = f"{brand} {random.choice(['Pro', 'Max', 'Ultra', 'Plus', 'Lite', '']) } {random.randint(11,15)}"
        elif category == "Laptops":
            name = f"{brand} {random.choice(['ProBook', 'Inspiron', 'Legion', 'ZenBook', 'MacBook', 'ThinkPad'])} {random.randint(13,17)}\""
        elif category in ["Headphones", "Earbuds"]:
            name = f"{brand} {random.choice(['Noise Cancelling', 'Wireless', 'Pro', 'Sport', 'Studio'])}"
        elif category == "Smart Watches":
            name = f"{brand} Watch {random.choice(['Series', 'Ultra', 'Active', 'Fit'])} {random.randint(4,9)}"
        else:
            name = f"{brand} {category} {fake.word().capitalize()} Edition"

        # Make name cleaner
        name = " ".join(name.split())

        # Revenue: very roughly realistic (monthly or lifetime depending on your context)
        if "iPhone" in name or "MacBook" in name or "Pro" in name:
            revenue = round(random.uniform(120000, 850000), 2)
        elif category in ["Smartphones", "Laptops", "Gaming Consoles"]:
            revenue = round(random.uniform(45000, 420000), 2)
        elif category in ["Headphones", "Earbuds", "Speakers"]:
            revenue = round(random.uniform(8000, 95000), 2)
        else:
            revenue = round(random.uniform(3000, 65000), 2)

        products.append({
            "name": name[:255],
            "category": category,
            "revenue": revenue
        })

    return products


def main():
    # Connect
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        create_table(engine)

        # Optional: uncomment if you want to start fresh every time
        # clear_table_if_exists(session)

        products = generate_products(1000)

        # Bulk insert
        session.bulk_insert_mappings(Product, products)
        session.commit()

        print(f"Successfully inserted {len(products)} products.")

    except Exception as e:
        session.rollback()
        print("Error occurred:", str(e))

    finally:
        session.close()


if __name__ == "__main__":
    main()