import pytest
from api_helpers import ApiWorld, build_world, make_app, make_client
from fastapi.testclient import TestClient

from netview.application.services import AppServices


@pytest.fixture
def world() -> ApiWorld:
    return build_world()


@pytest.fixture
def services(world: ApiWorld) -> AppServices:
    return world.services


@pytest.fixture
def client(world: ApiWorld) -> TestClient:
    return make_client(make_app(world))
