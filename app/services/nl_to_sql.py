"""
Natural language to SQL generation service.
"""

from app.services.llm_client import get_llm_client

SCHEMA_DESCRIPTION = """
You are generating SQL for a PostgreSQL database.

Available table:

products(
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    category VARCHAR,
    revenue FLOAT
)

Rules:
- Only generate a single SELECT query.
- Do NOT use INSERT, UPDATE, DELETE, DROP, or ALTER.
- Do NOT include explanations.
- Return SQL only.
"""


def generate_sql(question: str) -> str:
    """
    Converts natural-language question into safe SQL.

    Args:
        question (str): User question.

    Returns:
        str: Generated SQL query.
    """

    llm = get_llm_client()

    prompt = f"""
    {SCHEMA_DESCRIPTION}
    
    Question:
    {question}
    """

    sql = llm.complete(prompt)
    return sql.strip()
