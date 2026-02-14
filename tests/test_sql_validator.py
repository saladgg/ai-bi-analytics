import pytest
from app.services.sql_validator import validate_sql


def test_valid_select():
    validate_sql("SELECT * FROM products")


def test_reject_delete():
    with pytest.raises(ValueError):
        validate_sql("DELETE FROM products")


def test_reject_multiple_statements():
    with pytest.raises(ValueError):
        validate_sql("SELECT * FROM products; DROP TABLE users;")
