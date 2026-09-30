from collections.abc import Callable

import httpx
import pytest
import pytest_asyncio

from openlist_codex.client import OpenListClient
from openlist_codex.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(root="/Quark", token="test-secret", download_dir=tmp_path / "downloads")


@pytest_asyncio.fixture
async def make_client(settings):
    clients = []

    def create(handler: Callable, custom_settings: Settings | None = None):
        client = OpenListClient(custom_settings or settings, httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield create
    for client in clients:
        await client.close()
