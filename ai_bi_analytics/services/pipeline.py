"""
The NL → SQL → result pipeline (audit ARCH-1).

``QueryPipeline`` owns the orchestration that used to live in the route
handler: scope, cache lookup, SQL generation, the guard, execution and
explanation. Its collaborators are passed in (``api/deps.py`` assembles
them per request), so tests swap any of them through
``app.dependency_overrides`` instead of patching import paths.
"""

import hashlib
import logging

from opentelemetry import trace
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ai_bi_analytics.core import metrics
from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.schemas.query import QueryResponse
from ai_bi_analytics.services.cache import ResultCache
from ai_bi_analytics.services.llm_client import LLMClient
from ai_bi_analytics.services.query_executor import QueryExecutor, QueryResult
from ai_bi_analytics.services.schema_loader import SchemaProvider
from ai_bi_analytics.services.sql_validator import SQLGuard

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def question_log_fields(question: str, log_questions: bool) -> dict[str, object]:
    """
    Questions are user text and may contain personal or commercial details.
    Unless LOG_QUESTIONS is on, logs get a stable fingerprint (to spot
    repeats) and the length, not the text (audit OPS-2).
    """
    if log_questions:
        return {"question": question}
    return {
        "question_sha256": hashlib.sha256(question.encode()).hexdigest()[:16],
        "question_length": len(question),
    }


class QueryPipeline:
    def __init__(
        self,
        *,
        cfg: Settings,
        llm: LLMClient,
        schema: SchemaProvider,
        guard: SQLGuard,
        executor: QueryExecutor,
        cache: ResultCache,
    ) -> None:
        self._cfg = cfg
        self.llm = llm
        self.schema = schema
        self.guard = guard
        self.executor = executor
        self.cache = cache

    def run(
        self,
        question: str,
        *,
        db: Session,
        client_id: str,
        explain: bool = True,
    ) -> QueryResponse:
        """
        Answers a question. Typed errors (``AppError``) and database/Redis
        failures propagate; ``main.py`` maps them to client-safe responses
        (audit SEC-4).

        Each stage is a span (audit OPS-2); FastAPI's request span is the
        parent, and SQLAlchemy, Redis and LLM spans nest under the stages.
        """
        client = {"client_id": client_id}

        with tracer.start_as_current_span("query.scope"):
            scope = self.schema.get(db)

        with tracer.start_as_current_span("query.cache_lookup") as span:
            cache_key = self.cache.key(question, scope.fingerprint)
            cached = self._cached_response(cache_key)
            span.set_attribute("aibi.cache.hit", cached is not None)
        if cached is not None:
            metrics.queries.add(1, {**client, "source": "cache"})
            return self._complete_cached(cached, question, cache_key, explain)

        with tracer.start_as_current_span("query.generate_sql"):
            generated = self.llm.generate_sql(question, scope.description)

        with tracer.start_as_current_span("query.validate"):
            # Execute the guard's canonical SQL, never the raw model output.
            # The model saw exactly `scope`; the guard enforces the same scope.
            sql = self.guard.check(generated.sql, scope)

        with tracer.start_as_current_span("query.execute") as span:
            result = self.executor.run(db, sql)
            span.set_attribute("aibi.query.rows", len(result.rows))
            span.set_attribute("aibi.query.truncated", result.truncated)
        metrics.query_rows.record(len(result.rows))
        if result.truncated:
            metrics.query_truncations.add(1)

        usage = generated.usage
        explanation: str | None = None
        if explain:
            with tracer.start_as_current_span("query.explain"):
                explained = self.llm.explain(question, sql, result)
            explanation, usage = explained.text, usage + explained.usage

        logger.info(
            "Query executed",
            extra={
                **client,
                **question_log_fields(question, self._cfg.log_questions),
                "sql": sql,
                "tables_used": list(generated.tables_used),
                "row_count": len(result.rows),
                "truncated": result.truncated,
                "llm_input_tokens": usage.input_tokens,
                "llm_output_tokens": usage.output_tokens,
            },
        )
        metrics.queries.add(1, {**client, "source": "llm"})

        response = QueryResponse(
            sql=sql,
            result=result.rows,
            row_count=len(result.rows),
            truncated=result.truncated,
            explanation=explanation,
            assumptions=list(generated.assumptions),
        )
        self.cache.set(cache_key, response.model_dump(mode="json"))
        return response

    def _cached_response(self, key: str) -> QueryResponse | None:
        data = self.cache.get(key)
        if data is None:
            return None
        try:
            return QueryResponse.model_validate(data)
        except ValidationError:
            # e.g. written by an older version with a different shape.
            logger.warning("Ignoring cache entry with an unexpected shape")
            return None

    def _complete_cached(
        self, cached: QueryResponse, question: str, key: str, explain: bool
    ) -> QueryResponse:
        """
        A cached answer may have been stored without an explanation (an
        ``explain: false`` request). Explaining it now costs one LLM call
        instead of two, and the cache entry is upgraded for next time.
        """
        if not explain:
            return cached.model_copy(update={"explanation": None})
        if cached.explanation is not None:
            return cached
        result = QueryResult(rows=cached.result, truncated=cached.truncated)
        with tracer.start_as_current_span("query.explain"):
            explained = self.llm.explain(question, cached.sql, result)
        completed = cached.model_copy(update={"explanation": explained.text})
        self.cache.set(key, completed.model_dump(mode="json"))
        return completed
