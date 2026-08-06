"""User and session models."""

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


class UserPublic(BaseModel):
    user_id: str
    email: str | None = None
    display_name: str = ""


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


class AuthResponse(BaseModel):
    user: UserPublic
    token: str | None = None
