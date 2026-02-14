"""
SQL validation service.

Ensures generated SQL is safe and read-only before execution.
"""

FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
}


def validate_sql(sql: str) -> None:
    """
    Validates SQL query for safety constraints.

    Rules enforced:
    - Must start with SELECT
    - Must not contain mutation keywords
    - Must contain only one statement
    """

    normalized = sql.strip().upper()

    if not normalized.startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")

    if any(keyword in normalized for keyword in FORBIDDEN_KEYWORDS):
        raise ValueError("Forbidden SQL keyword detected.")

    if normalized.count(";") > 1:
        raise ValueError("Multiple SQL statements are not allowed.")

    # Basic comment stripping protection
    if "--" in normalized or "/*" in normalized:
        raise ValueError("SQL comments are not allowed.")
