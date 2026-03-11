import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app_module(monkeypatch):
    from app import main

    async def noop_async(*args, **kwargs):
        return 0

    monkeypatch.setattr(main.db, "connect", lambda: None)
    monkeypatch.setattr(main.db, "create_indexes", noop_async)
    monkeypatch.setattr(main.rate_limiter, "connect", noop_async)
    monkeypatch.setattr(main.rate_limiter, "close", noop_async)
    monkeypatch.setattr(main.db, "count_pending_commands", noop_async)
    return main


@pytest_asyncio.fixture
async def client(app_module):
    transport = ASGITransport(app=app_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
