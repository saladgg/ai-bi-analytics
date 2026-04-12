"""
Database models.

Defines SQLAlchemy ORM models representing
analytics-ready business entities.
"""

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    """
    Represents a product entity in the analytics database.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    revenue: Mapped[float] = mapped_column(Float)
