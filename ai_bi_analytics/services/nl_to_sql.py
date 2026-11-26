"""
Natural language to SQL generation service.
"""

from ai_bi_analytics.services.llm_client import get_llm_client

SQL_GENERATION_RULES = """
You are generating SQL for a PostgreSQL database.

Rules:
- Generate exactly one read-only query: SELECT, optionally with WITH
  (common table expressions) or UNION.
- Do NOT use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE,
  COPY, SELECT INTO, or FOR UPDATE.
- Only query the tables listed in the schema below.
- Output must contain SQL only.
- Do NOT wrap the query in markdown.
- Do NOT use triple backticks.
- Do NOT include explanations.
- Do NOT prefix with 'SQL'.
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
