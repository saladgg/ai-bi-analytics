from ai_bi_analytics.db.session import get_db


def test_get_db_yields_and_closes(monkeypatch):
    import ai_bi_analytics.db.session as session_mod

    class DummySession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    dummy_session = DummySession()

    monkeypatch.setattr(session_mod, "SessionLocal", lambda: dummy_session)

    gen = session_mod.get_db()
    db = next(gen)
    assert db is dummy_session
    assert dummy_session.closed is False

    gen.close()  # triggers the generator's `finally:` block
    assert dummy_session.closed is True

