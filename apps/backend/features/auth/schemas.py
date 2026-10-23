from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, StringConstraints

from core.schemas import CamelModel
from features.auth.status import AccountStatus

# Same rule as the frontend (PASSWORD_MIN_LENGTH in features/auth/schemas.ts); the upper bound keeps
# Argon2 from hashing megabytes sent on purpose.
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Token = Annotated[str, StringConstraints(min_length=16, max_length=128)]

# Same list as PROFESSIONS in apps/frontend/src/shared/api/contracts.ts.
Profession = Literal[
    "medical_biologist",
    "clinical_geneticist",
    "bioinformatician",
    "genetic_counselor",
    "researcher",
    "other",
]


class RegisterRequest(CamelModel):
    email:                  EmailStr
    password:               Password
    # One checkbox on the form; both dates are stored as proof.
    terms_accepted:         Literal[True]
    no_patient_data_pledge: Literal[True]


class LoginRequest(CamelModel):
    email:    EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    remember: bool = False


class EmailRequest(CamelModel):
    email: EmailStr


class TokenRequest(CamelModel):
    token: Token


class ResetPasswordRequest(CamelModel):
    token:    Token
    password: Password


class ChangePasswordRequest(CamelModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password:     Password


class DeleteAccountRequest(CamelModel):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class OnboardingRequest(CamelModel):
    full_name:    ShortText
    profession:   Profession
    organization: ShortText
    intended_use: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class UpdateProfileRequest(CamelModel):
    full_name:    ShortText | None = None
    profession:   Profession | None = None
    organization: ShortText | None = None


class UserResponse(CamelModel):
    id:           UUID
    email:        str
    full_name:    str
    role:         Literal["user", "admin"]
    status:       AccountStatus
    profession:   Profession | None  # null until onboarding is done
    organization: str | None


class AccessRequestResponse(CamelModel):
    """A completed profile waiting for an admin decision."""

    id:                UUID
    email:             str
    full_name:         str
    profession:        Profession | None
    organization:      str | None
    intended_use:      str | None
    email_verified_at: datetime | None
    created_at:        datetime


class RejectRequest(CamelModel):
    # Sent in the refusal e-mail.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class MessageResponse(CamelModel):
    message: str
