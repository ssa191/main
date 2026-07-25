"""Application configuration.

Values are read from environment variables (or a local .env file) so the same
code runs unchanged in development and production. In a real deployment you
would set SECRET_KEY and DATABASE_URL to strong/managed values.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Branding
    company_name: str = "Acme Industries"
    app_name: str = "Acme ERP"

    # Security
    secret_key: str = "dev-secret-change-me-in-production"
    access_token_expire_minutes: int = 60 * 8  # 8 hours

    # Database. Defaults to a local SQLite file so no DB server is required.
    # For Postgres in production, set e.g.
    #   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/erp
    database_url: str = "sqlite:///./erp.db"


settings = Settings()
