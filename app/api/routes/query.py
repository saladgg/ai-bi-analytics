import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import verify_api_key
from app.core.rate_limiter import enforce_rate_limit
from app.db.session import get_db
from app.schemas.query import QueryRequest, QueryResponse
from app.services.cache import (
    generate_cache_key,
    get_cached_response,
    set_cached_response,
)
from app.services.explanation import explain_result
from app.services.nl_to_sql import generate_sql
from app.services.query_executor import execute_query
from app.services.schema_loader import load_schema_metadata
from app.services.sql_validator import validate_sql

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query_database(
    request: Request,
    payload: QueryRequest,
    db: Session = Depends(get_db),  # noqa B008
    _: None = Depends(verify_api_key),
):
    """
    Full NL → SQL → Execute pipeline.
    """
    enforce_rate_limit(request)
    try:
        schema_description = load_schema_metadata(db)
        cache_key = generate_cache_key(payload.question + "|" + schema_description)
        cached = get_cached_response(cache_key)
        if cached:
            return cached

        sql = generate_sql(payload.question, schema_description)
        validate_sql(sql)
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

        response = QueryResponse(
            sql=sql,
            result=result,
            explanation=explanation,
        )

        set_cached_response(
            cache_key,
            response.model_dump(),
        )

        return response

    except Exception as exc:
        logger.error("Request failure: %s", str(exc))
        raise HTTPException(status_code=400, detail=str(exc))  # noqa B008
