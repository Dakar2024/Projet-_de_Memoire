from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": the shared .env also holds compose-only keys (API_PORT, DB_PORT).
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str  = "Genomica"
    APP_ENV:  str  = "development"
    DEBUG:    bool = False

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database
    POSTGRES_HOST:     str = "localhost"
    POSTGRES_PORT:     int = 5432
    POSTGRES_USER:     str
    POSTGRES_PASSWORD: str
    POSTGRES_DB:       str

    # Auth
    SECRET_KEY:                  str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day, session cookie
    SESSION_REMEMBER_DAYS:       int = 30       # "remember me" checked: persistent cookie
    VERIFICATION_TOKEN_HOURS:    int = 48
    RESET_TOKEN_MINUTES:         int = 60

    # Client IP for rate limits. The frontend server calls this API for every user, so the socket
    # address is always its own: trust the last X-Forwarded-For entry only when the API is reachable
    # from that server alone (true in compose, never when the port is public).
    TRUST_FORWARDED_FOR: bool = False

    # Seed admin (created on startup if missing)
    ADMIN_EMAIL:    str
    ADMIN_PASSWORD: str
    ADMIN_NAME:     str = "Administrateur"

    # Mail — Resend SMTP, same provider as the pipeline alerts. Port 465 is implicit TLS
    # (MAIL_USE_TLS), not STARTTLS: set MAIL_STARTTLS=true only for a 587 server.
    MAIL_SERVER:   str  = "smtp.resend.com"
    MAIL_PORT:     int  = 465
    MAIL_USERNAME: str  = "resend"
    MAIL_PASSWORD: str  = ""
    MAIL_FROM:     str  = ""
    MAIL_USE_TLS:  bool = True
    MAIL_STARTTLS: bool = False

    # Redis (Huey task queue, rate limit counters)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"


settings = Settings()
