import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 60


class ApiError(Exception):
    """A failed call, with what the API said about it."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id


def _error_from_response(response: requests.Response) -> ApiError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI request validation errors
        detail = "; ".join(str(item.get("msg", item)) for item in detail)
    if response.status_code == 429:
        retry = response.headers.get("Retry-After")
        detail = "Rate limit reached." + (f" Try again in {retry}s." if retry else "")
    return ApiError(
        str(detail or f"The API returned HTTP {response.status_code}."),
        status=response.status_code,
        code=body.get("code") if isinstance(body, dict) else None,
        request_id=response.headers.get("x-request-id"),
    )


def call_backend(question: str, *, explain: bool = True) -> dict:
    if not API_KEY:
        raise ApiError("Set API_KEY (a client key from API_KEYS) for the demo UI.")
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/query",
            json={"question": question, "explain": explain},
            headers={"x-api-key": API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Can't reach the API at {API_BASE_URL}: {exc}") from exc

    if response.status_code != 200:
        raise _error_from_response(response)
    return response.json()
