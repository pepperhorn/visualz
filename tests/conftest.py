import pytest
from aiohttp.test_utils import TestClient, TestServer

from visualz.server import create_app
from visualz.state import Store


@pytest.fixture
async def api(tmp_path):
    store = Store(tmp_path)
    async with TestClient(TestServer(create_app(store))) as client:
        yield client, store
    store.close()
