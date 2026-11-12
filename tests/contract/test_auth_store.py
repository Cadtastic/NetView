import pytest

from .auth_store_contract import ALL_CHECKS


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_auth_store_contract(check, store_factory):
    check(store_factory)
