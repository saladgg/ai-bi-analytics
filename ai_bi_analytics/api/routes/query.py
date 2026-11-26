import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ai_bi_analytics.api.deps import verify_api_key
from ai_bi_analytics.core.rate_limiter import enforce_rate_limit
from ai_bi_analytics.db.session import get_db
from ai_bi_analytics.schemas.query import QueryRequest, QueryResponse
from ai_bi_analytics.services.cache import (
    generate_cache_key,
    get_cached_response,
    set_cached_response,
)
from ai_bi_analytics.services.explanation import explain_result
from ai_bi_analytics.services.nl_to_sql import generate_sql
from ai_bi_analytics.services.query_executor import execute_query
from ai_bi_analytics.services.schema_loader import (
    load_schema_metadata,
    load_table_names,
)
from ai_bi_analytics.services.sql_validator import validate_sql

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query_database(
    request: Request,
    response: Response,
    payload: QueryRequest,
    db: Session = Depends(get_db),  # noqa B008
    _: None = Depends(verify_api_key),
):
    """
    Full NL → SQL → Execute pipeline.
    """
    rate_limit = enforce_rate_limit(request)
    response.headers.update(rate_limit.headers())

    # No blanket try/except: typed errors and DB/Redis failures are mapped
    # to client-safe responses by the handlers in main.py (audit SEC-4).
    schema_description = load_schema_metadata(db)
    cache_key = generate_cache_key(payload.question + "|" + schema_description)
    cached = get_cached_response(cache_key)
    if cached:
        return cached

    generated_sql = generate_sql(payload.question, schema_description)
    # Execute the guard's canonical SQL, never the raw model output.
    sql = validate_sql(generated_sql, allowed_tables=load_table_names(db))
    result = execute_query(db, sql)
    explanation = explain_result(payload.question, sql, result)

    logger.info(
        "Query executed",
        extra={
            "question": payload.question,
            "sql": sql,
            "row_count": len(result),
        },
    )

    query_response = QueryResponse(
        sql=sql,
        result=result,
        explanation=explanation,
    )

    set_cached_response(
        cache_key,
        query_response.model_dump(mode="json"),
    )

    return query_response
