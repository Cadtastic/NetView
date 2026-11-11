import pydantic
from pydantic import BaseModel, SecretStr

from netview.infrastructure.plugins.settings_codec import (
    MASK,
    dump_for_display,
    dump_for_storage,
    mask_raw,
    merge_patch,
    safe_validation_message,
)


class M(BaseModel):
    host: str = "h"
    key: SecretStr | None = None


class Required(BaseModel):
    pw: SecretStr
    n: int = 1


def test_storage_reveals_secret() -> None:
    assert dump_for_storage(M(key=SecretStr("s3")))["key"] == "s3"


def test_display_masks_secret() -> None:
    assert dump_for_display(M(key=SecretStr("s3")))["key"] == "********"
    assert dump_for_display(M())["key"] is None
    assert MASK == "********"


def test_patch_with_mask_keeps_secret() -> None:
    assert merge_patch({"host": "h", "key": "s3"}, {"key": "********", "host": "x"}, M) == {
        "host": "x",
        "key": "s3",
    }


def test_omitted_secret_keeps_secret() -> None:
    assert merge_patch({"key": "s3"}, {"host": "y"}, M)["key"] == "s3"


def test_blank_secret_keeps_secret() -> None:
    assert merge_patch({"key": "s3"}, {"key": ""}, M)["key"] == "s3"


def test_none_clears_secret() -> None:
    assert merge_patch({"key": "s3"}, {"key": None}, M)["key"] is None


def test_new_value_replaces_secret() -> None:
    assert merge_patch({"key": "s3"}, {"key": "new"}, M)["key"] == "new"


def test_nested_and_optional_detection() -> None:
    assert mask_raw({"host": "h", "key": "s3"}, M) == {"host": "h", "key": "********"}
    assert mask_raw({"host": "h", "key": None}, M)["key"] is None
    assert mask_raw({"pw": 12345}, Required) == {"pw": "********"}
    assert mask_raw({"n": 2}, Required) == {"n": 2}
    assert dump_for_display(Required(pw=SecretStr("x")))["pw"] == "********"


def test_safe_validation_message_has_no_input() -> None:
    try:
        Required.model_validate({"pw": "topsecret", "n": "not-an-int"})
    except pydantic.ValidationError as exc:
        msg = safe_validation_message(exc)
    assert "n" in msg
    assert "not-an-int" not in msg
    assert "topsecret" not in msg
