"""
Natural language to SQL generation service.
"""

from app.services.llm_client import get_llm_client

SQL_GENERATION_RULES = """
You are generating SQL for a PostgreSQL database.

Rules:
- Only generate a single SELECT statement.
- Do NOT use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.
- Output must contain SQL only.
- Do NOT wrap the query in markdown.
- Do NOT use triple backticks.
- Do NOT include explanations.
- Do NOT prefix with 'SQL'.
- Must begin directly with SELECT.
- Only one statement allowed.
"""


def generate_sql(question: str, schema_description: str) -> str:
    """
    Converts natural-language question into safe SQL.

    Args:
        question (str): User question.
        schema_description (str): Dynamically loaded schema metadata.

    Returns:
        str: Generated SQL query.
    """

    llm = get_llm_client()

    prompt = f"""
    {SQL_GENERATION_RULES}
    
    Available database schema:
    {schema_description}
    
    User Question:
    {question}
    """

    sql = llm.complete(prompt)
    return sql.strip()
