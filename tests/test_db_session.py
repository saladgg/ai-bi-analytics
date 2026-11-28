from types import SimpleNamespace

from ai_bi_analytics.api.deps import get_db


def test_get_db_yields_and_closes():
    class DummySession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    dummy_session = DummySession()
    resources = SimpleNamespace(session_factory=lambda: dummy_session)

    gen = get_db(resources)  # type: ignore[arg-type]
    db = next(gen)
    assert db is dummy_session
    assert dummy_session.closed is False

    gen.close()  # triggers the generator's `finally:` block
    assert dummy_session.closed is True
