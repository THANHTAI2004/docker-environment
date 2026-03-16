import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app_module(monkeypatch):
    from app import main
    from app.utils.auth import _db_now

    async def noop_async(*args, **kwargs):
        return 0

    sessions = {}

    async def create_auth_session(doc):
        sessions[doc["session_id"]] = dict(doc)
        return True

    async def get_auth_session(session_id):
        return sessions.get(session_id)

    async def get_auth_session_by_refresh_token_hash(refresh_token_hash):
        for session in sessions.values():
            if session.get("refresh_token_hash") == refresh_token_hash:
                return session
        return None

    async def rotate_auth_session(session_id, current_refresh_token_hash, new_refresh_token_hash, expires_at):
        session = sessions.get(session_id)
        if not session:
            return False
        if session.get("refresh_token_hash") != current_refresh_token_hash:
            return False
        if session.get("revoked_at") is not None:
            return False
        if session.get("expires_at") and session["expires_at"] <= _db_now():
            return False
        session["refresh_token_hash"] = new_refresh_token_hash
        session["expires_at"] = expires_at
        session["last_refreshed_at"] = _db_now()
        return True

    async def revoke_auth_session(session_id, reason, revoked_by=None):
        session = sessions.get(session_id)
        if not session or session.get("revoked_at") is not None:
            return False
        session["revoked_at"] = _db_now()
        session["revoked_reason"] = reason
        session["revoked_by"] = revoked_by
        return True

    monkeypatch.setattr(main.db, "connect", lambda: None)
    monkeypatch.setattr(main.db, "create_indexes", noop_async)
    monkeypatch.setattr(main.rate_limiter, "connect", noop_async)
    monkeypatch.setattr(main.rate_limiter, "close", noop_async)
    monkeypatch.setattr(main.db, "count_pending_commands", noop_async)
    monkeypatch.setattr(main.db, "create_auth_session", create_auth_session)
    monkeypatch.setattr(main.db, "get_auth_session", get_auth_session)
    monkeypatch.setattr(main.db, "get_auth_session_by_refresh_token_hash", get_auth_session_by_refresh_token_hash)
    monkeypatch.setattr(main.db, "rotate_auth_session", rotate_auth_session)
    monkeypatch.setattr(main.db, "revoke_auth_session", revoke_auth_session)
    return main


@pytest_asyncio.fixture
async def client(app_module):
    transport = ASGITransport(app=app_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
