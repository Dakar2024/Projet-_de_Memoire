from piccolo.columns import UUID, ForeignKey, Integer, Text, Timestamptz, Varchar
from piccolo.columns.base import OnDelete
from piccolo.table import Table

from features.auth.status import AccountStatus


class User(Table, tablename="users"):
    id                        = UUID(primary_key=True)
    email                     = Varchar(length=320, unique=True, index=True)  # stored lower-case
    hashed_password           = Varchar(length=255)
    full_name                 = Varchar(length=255, default="")
    role                      = Varchar(length=16, default="user")  # admin | user
    # Single source of truth for access; only AuthService.transition() writes it.
    status                    = Varchar(length=32, default=AccountStatus.PENDING_EMAIL.value, index=True)
    profession                = Varchar(length=64, null=True, default=None)
    organization              = Varchar(length=255, null=True, default=None)
    intended_use              = Text(null=True, default=None)
    email_verified_at         = Timestamptz(null=True, default=None)
    approved_at               = Timestamptz(null=True, default=None)
    approved_by               = ForeignKey(references="self", null=True, default=None, on_delete=OnDelete.set_null)
    last_login_at             = Timestamptz(null=True, default=None)
    rejection_reason          = Text(null=True, default=None)
    terms_accepted_at         = Timestamptz(null=True, default=None)
    no_patient_data_pledge_at = Timestamptz(null=True, default=None)
    daily_quota_override      = Integer(null=True, default=None)
    # Copied into the session token as `tv`; bumping it signs out every existing session.
    token_version             = Integer(default=0)
    created_at                = Timestamptz(auto_now_add=True)


class EmailVerificationToken(Table, tablename="email_verification_tokens"):
    id         = UUID(primary_key=True)
    user       = ForeignKey(references=User, on_delete=OnDelete.cascade)
    token_hash = Varchar(length=64, unique=True, index=True)  # SHA-256, never the token itself
    expires_at = Timestamptz()
    used_at    = Timestamptz(null=True, default=None)
    created_at = Timestamptz(auto_now_add=True)


class PasswordResetToken(Table, tablename="password_reset_tokens"):
    id         = UUID(primary_key=True)
    user       = ForeignKey(references=User, on_delete=OnDelete.cascade)
    token_hash = Varchar(length=64, unique=True, index=True)  # SHA-256, never the token itself
    expires_at = Timestamptz()
    used_at    = Timestamptz(null=True, default=None)
    created_at = Timestamptz(auto_now_add=True)
