"""User and session models."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


LOCAL_DEFAULT_USER_ID = "local-default"


def _normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Invalid email address")
    local, _, domain = email.partition("@")
    if not local or not domain or " " in email:
        raise ValueError("Invalid email address")
    return email


def _normalize_timezone(value: str) -> str:
    timezone_name = (value or "").strip()
    if not timezone_name or len(timezone_name) > 128:
        raise ValueError("Invalid timezone")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Invalid IANA timezone") from exc
    return timezone_name


class UserPublic(BaseModel):
    user_id: str
    email: str | None = None
    display_name: str = ""
    timezone_name: str = "UTC"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class TimezoneUpdateRequest(BaseModel):
    timezone_name: str = Field(min_length=1, max_length=128)

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _normalize_timezone(value)


class AuthResponse(BaseModel):
    user: UserPublic
    token: str | None = None
