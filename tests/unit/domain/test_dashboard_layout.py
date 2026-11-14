import pytest

from netview.domain.dashboard import layout_to_dict, parse_layout
from netview.domain.errors import ValidationError

LAT = "9f4cd689-1a67-4c89-abff-ac9252568d97.card.latency"


def test_round_trip_keeps_order_hidden_spans_and_group():
    raw = {
        "version": 1,
        "order": ["core.tile.online", LAT],
        "hidden": ["core.card.events"],
        "spans": {LAT: "half"},
        "group": "plugin_type",
    }
    layout = parse_layout(raw)
    assert layout_to_dict(layout) == raw


def test_bad_values_name_their_field():
    for raw, field in [
        ({"version": 2, "order": [], "hidden": [], "spans": {}, "group": "none"}, "version"),
        ({"version": 1, "order": [], "hidden": [], "spans": {}, "group": "type"}, "group"),
        (
            {"version": 1, "order": [], "hidden": [], "spans": {"core.card.x": "wide"}, "group": "none"},
            "spans",
        ),
        ({"version": 1, "order": ["core.widget.x"], "hidden": [], "spans": {}, "group": "none"}, "order"),
        ({"version": 1, "order": [], "hidden": ["Core.tile.x"], "spans": {}, "group": "none"}, "hidden"),
        ("not a dict", "layout"),
    ]:
        with pytest.raises(ValidationError) as e:
            parse_layout(raw)
        assert field in e.value.fields


def test_dots_and_dashes_in_the_item_id_are_allowed():
    parse_layout(
        {
            "version": 1,
            "order": ["core.card.top-uploader", "core.tile.dns.v2"],
            "hidden": [],
            "spans": {},
            "group": "none",
        }
    )


def test_more_than_500_keys_is_refused():
    keys = [f"core.tile.t{i}" for i in range(501)]
    with pytest.raises(ValidationError):
        parse_layout({"version": 1, "order": keys, "hidden": [], "spans": {}, "group": "none"})


def test_a_record_over_64_kb_is_refused_even_within_500_keys():
    guid = "c66a564b-0254-44cf-bb74-1c7f6ebae6be"
    keys = [f"{guid}.card.{i:03d}{'x' * 97}" for i in range(500)]  # 500 keys, about 72 KB serialized
    with pytest.raises(ValidationError) as e:
        parse_layout({"version": 1, "order": keys, "hidden": [], "spans": {}, "group": "none"})
    assert "layout" in e.value.fields


def test_duplicate_keys_keep_their_first_position():
    layout = parse_layout(
        {
            "version": 1,
            "order": ["core.tile.a", "core.tile.b", "core.tile.a"],
            "hidden": [],
            "spans": {},
            "group": "none",
        }
    )
    assert layout.order == ("core.tile.a", "core.tile.b")
