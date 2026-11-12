"""Capability poll jobs: the host schedules one per provider, under the plugin's own id."""

from conftest import HostEnv
from sample_plugins.pollers import PollerPlugin, ReservedJobPlugin

from netview.application.capabilities import Capability
from netview.application.plugins.jobs import JobSpec


class Poller:
    def __init__(self) -> None:
        self.seen: list[tuple[str, Capability]] = []

    def __call__(self, plugin_id: str, capability: Capability, provider: object) -> JobSpec | None:
        self.seen.append((plugin_id, capability))
        if capability is Capability.HEALTH:
            return JobSpec("poll.health", 5.0, lambda: None)
        return None


def _adds(env: HostEnv) -> set[tuple[str, str]]:
    return {(owner, name) for kind, owner, name in env.scheduler.calls if kind == "add"}


def test_a_health_provider_gets_a_poll_job_next_to_its_own(env: HostEnv) -> None:
    poller = Poller()
    host = env.host([PollerPlugin], poller=poller)
    host.load_all()
    host.start_jobs()

    pid = env.id(PollerPlugin)
    assert _adds(env) == {(pid, "own"), (pid, "poll.health")}
    assert poller.seen == [(pid, Capability.HEALTH)]


def test_the_poll_job_survives_a_settings_change(env: HostEnv) -> None:
    host = env.host([PollerPlugin], poller=Poller())
    host.load_all()
    host.start_jobs()
    env.scheduler.calls.clear()

    host.update_settings(env.id(PollerPlugin), {"x": 2})

    pid = env.id(PollerPlugin)
    assert env.scheduler.calls[0][:2] == ("remove_owner", pid)
    assert _adds(env) == {(pid, "own"), (pid, "poll.health")}


def test_without_a_poller_only_the_plugins_own_jobs_run(env: HostEnv) -> None:
    host = env.host([PollerPlugin])
    host.load_all()
    host.start_jobs()
    assert _adds(env) == {(env.id(PollerPlugin), "own")}


def test_a_provider_the_poller_does_not_want_adds_no_job(env: HostEnv) -> None:
    host = env.host([PollerPlugin], poller=lambda *_: None)
    host.load_all()
    host.start_jobs()
    assert _adds(env) == {(env.id(PollerPlugin), "own")}


def test_a_plugin_job_named_poll_something_is_refused(env: HostEnv) -> None:
    host = env.host([ReservedJobPlugin])
    host.load_all()
    info = host.get(env.id(ReservedJobPlugin))
    assert info.state == "failed"
    assert info.error == 'job name "poll.x" is reserved'
    assert env.registry.providers(Capability.HEALTH) == []
