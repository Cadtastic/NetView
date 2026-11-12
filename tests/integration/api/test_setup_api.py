import threading

from api_helpers import PASSWORD, ApiWorld, build_world, make_app, make_client


def open_world() -> ApiWorld:
    return build_world(seed_admin=False)


def test_setup_open_redirects_pages_and_409s_api() -> None:
    anon = make_client(make_app(open_world()), user=None)
    page = anon.get("/", follow_redirects=False)
    assert (page.status_code, page.headers["location"]) == (303, "/setup")
    login_page = anon.get("/login", follow_redirects=False)
    assert (login_page.status_code, login_page.headers["location"]) == (303, "/setup")
    api = anon.get("/api/v1/state")
    assert api.status_code == 409
    assert api.json() == {"error": "setup required"}
    assert anon.post("/api/v1/scan").status_code == 409
    assert anon.get("/api/v1/setup").json() == {"open": True, "code_required": False}
    assert anon.get("/static/js/main.js").status_code == 200


def test_setup_post_signs_in_and_closes_setup() -> None:
    world = open_world()
    app = make_app(world)
    client = make_client(app, user=None)
    done = client.post("/api/v1/setup", json={"username": " Admin ", "password": PASSWORD})
    assert done.status_code == 200
    assert done.json()["username"] == "admin"
    assert done.json()["is_admin"] is True
    assert "HttpOnly" in done.headers["set-cookie"]
    assert client.get("/api/v1/state").status_code == 200
    assert client.get("/api/v1/setup").json()["open"] is False
    again = make_client(app, user=None).post("/api/v1/setup", json={"username": "x", "password": PASSWORD})
    assert again.status_code == 401
    assert (
        make_client(app, user=None).get("/", follow_redirects=False).headers["location"].startswith("/login")
    )


def test_setup_rejects_a_short_password() -> None:
    client = make_client(make_app(open_world()), user=None)
    response = client.post("/api/v1/setup", json={"username": "admin", "password": "short"})
    assert response.status_code == 422
    assert "password" in response.json()["fields"]


def test_setup_race_one_wins() -> None:
    world = open_world()
    app = make_app(world)
    barrier = threading.Barrier(2, timeout=5)
    original = world.hasher.hash

    def slow_hash(password: str) -> str:
        barrier.wait()  # both requests pass the "is setup open" check before either creates the admin
        return original(password)

    world.hasher.hash = slow_hash  # type: ignore[method-assign]
    statuses: list[int] = []

    def attempt(name: str) -> None:
        client = make_client(app, user=None)
        statuses.append(
            client.post("/api/v1/setup", json={"username": name, "password": PASSWORD}).status_code
        )

    threads = [threading.Thread(target=attempt, args=(n,)) for n in ("first", "second")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(statuses) == [200, 409]
    assert len(world.auth.users.list()) == 1
