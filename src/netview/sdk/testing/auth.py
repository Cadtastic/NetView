"""Sign-in for tests that drive a whole NetView app: every request needs a signed-in user."""

from netview.application.auth.principal import SYSTEM_PRINCIPAL
from netview.application.services import AppServices
from netview.domain.auth import ADMIN_ROLE

TEST_PASSWORD = "correct horse battery"
SESSION_COOKIE = "netview_session"


def admin_cookies(services: AppServices, username: str = "tester") -> dict[str, str]:
    """Make an administrator in the app's own auth store and return a session cookie for a test client."""
    auth = services.auth
    assert auth is not None, "this app has no sign-in"
    user = auth.users.create_local(SYSTEM_PRINCIPAL, username, "", TEST_PASSWORD, {ADMIN_ROLE})
    auth.users.reset_password(SYSTEM_PRINCIPAL, user.id, TEST_PASSWORD, must_change=False)
    return {SESSION_COOKIE: auth.sessions.create(user.id, "testclient", "pytest")}
