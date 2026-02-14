import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import verify_api_key
from app.db.session import get_db
from app.schemas.query import QueryRequest, QueryResponse
from app.services.explanation import explain_result
from app.services.nl_to_sql import generate_sql
from app.services.query_executor import execute_query
from app.services.sql_validator import validate_sql

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query_database(
    payload: QueryRequest,
    db: Session = Depends(get_db),  # noqa B008
    _: None = Depends(verify_api_key),
):
    """
    Full NL → SQL → Execute pipeline.
    """

    try:
        sql = generate_sql(payload.question)
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

        return QueryResponse(
            sql=sql,
            result=result,
            explanation=explanation,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))  # noqa B008
