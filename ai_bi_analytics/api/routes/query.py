from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ai_bi_analytics.api.deps import get_db, get_query_pipeline, rate_limited_client
from ai_bi_analytics.core.security import Principal
from ai_bi_analytics.schemas.query import QueryRequest, QueryResponse
from ai_bi_analytics.services.pipeline import QueryPipeline

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query_database(
    payload: QueryRequest,
    principal: Principal = Depends(rate_limited_client),
    db: Session = Depends(get_db),
    pipeline: QueryPipeline = Depends(get_query_pipeline),
) -> QueryResponse:
    """
    Answers a natural-language question: NL → SQL → guard → execute →
    explanation (see ``services/pipeline.py``).
    """
    return pipeline.run(
        payload.question,
        db=db,
        client_id=principal.client_id,
        explain=payload.explain,
    )
