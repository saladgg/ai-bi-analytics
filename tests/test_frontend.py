"""
Streamlit demo helpers (audit CQ-3). Skipped without the `frontend`
dependency group.
"""

import importlib.util
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")
requests = pytest.importorskip("requests")

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def load(name):
    # By path: the demo's modules are top-level `api` and `utils`.
    spec = importlib.util.spec_from_file_location(
        f"frontend_{name}", FRONTEND / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


utils = load("utils")
api = load("api")


# ---------------------------------------------------------------------------
# auto_chart
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frame, expected",
    [
        # The old code read columns 2 and 3 and crashed on these.
        ({"name": ["a", "b"], "revenue": [1, 2]}, ("name", "revenue")),
        (
            {"id": [1, 2], "name": ["a", "b"], "revenue": [1.0, 2.0]},
            ("name", "revenue"),
        ),
        ({"customer_id": [7, 8], "total": [1, 2]}, None),
        ({"year": [2024, 2025], "revenue": [1, 2]}, ("year", "revenue")),
        ({"name": ["a"], "active": [True]}, None),
        ({"name": ["a"], "city": ["x"]}, None),
        ({"revenue": [1, 2]}, None),
    ],
)
def test_chart_columns(frame, expected):
    assert utils.pick_chart_columns(pd.DataFrame(frame)) == expected


def test_auto_chart_draws_label_against_measure():
    fig = utils.auto_chart(pd.DataFrame({"name": ["a", "b"], "revenue": [1, 2]}))

    assert fig is not None
    assert fig.layout.title.text == "revenue by name"


@pytest.mark.parametrize(
    "frame", [pd.DataFrame(), pd.DataFrame({"name": ["a"], "city": ["x"]})]
)
def test_auto_chart_skips_unchartable_results(frame):
    assert utils.auto_chart(frame) is None


# ---------------------------------------------------------------------------
# call_backend
# ---------------------------------------------------------------------------


class Response:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


@pytest.fixture()
def post(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "API_KEY", "k")
    monkeypatch.setattr(api, "API_BASE_URL", "http://api")

    def respond_with(response):
        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(api.requests, "post", fake_post)
        return calls

    return respond_with


def test_posts_to_the_route_without_a_trailing_slash(post):
    calls = post(Response(200, {"sql": "SELECT 1"}))

    assert api.call_backend("q", explain=False) == {"sql": "SELECT 1"}
    url, kwargs = calls[0]
    assert url == "http://api/api/query"
    assert kwargs["json"] == {"question": "q", "explain": False}
    assert kwargs["headers"] == {"x-api-key": "k"}


def test_api_error_body_becomes_a_friendly_error(post):
    post(
        Response(
            422,
            {"detail": "The generated query was rejected.", "code": "unsafe_sql"},
            {"x-request-id": "abc"},
        )
    )

    with pytest.raises(api.ApiError) as exc:
        api.call_backend("q")

    assert (exc.value.message, exc.value.code, exc.value.request_id) == (
        "The generated query was rejected.",
        "unsafe_sql",
        "abc",
    )


def test_validation_errors_are_joined(post):
    post(Response(422, {"detail": [{"msg": "too short"}, {"msg": "bad"}]}))

    with pytest.raises(api.ApiError, match="too short; bad"):
        api.call_backend("q")


def test_rate_limit_mentions_retry_after(post):
    post(Response(429, {"detail": "Rate limit exceeded"}, {"Retry-After": "12"}))

    with pytest.raises(api.ApiError, match="Try again in 12s"):
        api.call_backend("q")


def test_non_json_error(post):
    post(Response(502))

    with pytest.raises(api.ApiError, match="HTTP 502"):
        api.call_backend("q")


def test_unreachable_api(post):
    post(requests.ConnectionError("refused"))

    with pytest.raises(api.ApiError, match="Can't reach the API at http://api"):
        api.call_backend("q")


def test_missing_key(monkeypatch):
    monkeypatch.setattr(api, "API_KEY", None)

    with pytest.raises(api.ApiError, match="Set API_KEY"):
        api.call_backend("q")
