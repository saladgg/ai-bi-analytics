"""
Explanation service.

Generates business-readable explanations for query results
using LLM while grounding output in actual SQL + returned data.
"""

from app.services.llm_client import get_llm_client


def explain_result(question: str, sql: str, result: list[dict]) -> str:
    """
    Generates an explanation of the query result.

    Args:
        question (str): Original user question.
        sql (str): Executed SQL query.
        result (list[dict]): Query results.

    Returns:
        str: Business-readable explanation.
    """

    llm = get_llm_client()

    prompt = f"""
    You are explaining database query results to a business user.
    
    Original question:
    {question}
    
    Executed SQL:
    {sql}
    
    Query result:
    {result}
    
    Rules:
    - Only explain what is present in the results.
    - Do not invent data.
    - Keep explanation concise and factual.
    """

    return llm.complete(prompt)
