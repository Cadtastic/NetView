from typing import Annotated

import pydantic
from pydantic import BaseModel, Field, SecretBytes, SecretStr

from netview.infrastructure.plugins.settings_codec import (
    MASK,
    dump_for_display,
    dump_for_storage,
    mask_raw,
    merge_patch,
    safe_validation_message,
    unsupported_secrets,
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


class AnnotatedSecret(BaseModel):
    key: Annotated[SecretStr, Field(min_length=1)] | None = None
    other: Annotated[SecretStr | None, Field(description="d")] = None


def test_annotated_secrets_are_masked() -> None:
    model = AnnotatedSecret(key=SecretStr("s3"), other=SecretStr("s4"))
    assert dump_for_display(model) == {"key": MASK, "other": MASK}
    assert dump_for_storage(model) == {"key": "s3", "other": "s4"}
    assert mask_raw({"key": "s3", "other": "s4"}, AnnotatedSecret) == {"key": MASK, "other": MASK}
    assert unsupported_secrets(AnnotatedSecret) == []


def test_top_level_secretstr_is_supported() -> None:
    assert unsupported_secrets(M) == []
    assert unsupported_secrets(Required) == []


class Inner(BaseModel):
    pw: SecretStr


class Nested(BaseModel):
    inner: Inner | None = None


class InList(BaseModel):
    keys: list[SecretStr] = []


class InDict(BaseModel):
    keys: dict[str, SecretStr] = {}


class Bytes(BaseModel):
    blob: SecretBytes | None = None


def test_unmaskable_secret_shapes_are_reported() -> None:
    assert unsupported_secrets(Nested) == ["$defs.Inner.properties.pw"]
    assert unsupported_secrets(InList) == ["properties.keys.items"]
    assert unsupported_secrets(InDict) == ["properties.keys.additionalProperties"]
    assert unsupported_secrets(Bytes) == ["properties.blob.anyOf[0]"]
