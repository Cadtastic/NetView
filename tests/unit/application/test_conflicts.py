from netview.application.plugins.conflicts import Candidate, pick_winners

G = "11111111-1111-4111-8111-111111111111"


def cand(key: str, tier: int, folder: str | None, guid: str | None = G) -> Candidate:
    return Candidate(key, guid, tier, folder)


def test_builtin_beats_folder() -> None:
    builtin = cand("entry_point:x", 0, None)
    folder = cand("folder:/a", 1, "/a")
    winners, losers = pick_winners([folder, builtin], {G: "/a"})
    assert winners == [builtin]
    assert losers == {"folder:/a": builtin}


def test_last_folder_beats_tier() -> None:
    low = cand("folder:/a", 1, "/a")
    high = cand("folder:/b", 2, "/b")
    winners, losers = pick_winners([low, high], {G: "/b"})
    assert winners == [high]
    assert losers == {"folder:/a": high}


def test_plugin_dirs_beats_data_dir() -> None:
    data = cand("folder:/a", 2, "/a")
    dirs = cand("folder:/z", 1, "/z")
    winners, _ = pick_winners([data, dirs], {})
    assert winners == [dirs]


def test_path_breaks_ties() -> None:
    b = cand("folder:/b", 1, "/b")
    a = cand("folder:/a", 1, "/a")
    winners, losers = pick_winners([b, a], {})
    assert winners == [a]
    assert losers == {"folder:/b": a}


def test_no_guid_is_neither_winner_nor_loser() -> None:
    bad = cand("folder:/x", 1, "/x", guid=None)
    winners, losers = pick_winners([bad], {})
    assert winners == [] and losers == {}
