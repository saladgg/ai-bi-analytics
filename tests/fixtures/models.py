"""
Test-only ORM model: the ``products`` table the suite queries. The app
itself never maps tables; it introspects whatever the database has
(audit CQ-2 moved this out of the package).
"""

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    revenue: Mapped[float] = mapped_column(Float)
