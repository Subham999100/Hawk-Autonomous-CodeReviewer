from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Information
    app_name: str = "Hawk"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./hawk.db"
    database_sync_url: str = "sqlite:///./hawk.db"

    # Redis Queue & PubSub
    redis_url: str = "redis://localhost:6379/0"

    # Authentication & Authorization
    auth_provider: str = "jwt"  # "jwt" (Managed IdP or local token engine)
    auth_secret_key: str = "hawk-super-secret-development-key-change-in-production-32chars"
    auth_algorithm: str = "HS256"
    auth_access_token_expire_minutes: int = 1440  # 24 hours
    auth_jwks_url: str = ""  # If using RS256/OIDC from Supabase/Clerk/Auth0
    auth_issuer: str = ""
    auth_audience: str = ""

    # OpenAI Reasoning
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    # GitHub Access (Optional PAT for higher rate limits)
    github_token: str = ""

    # Jev Orchestration (TypeSafe AI System One decision API)
    jev_api_key: str = ""
    jev_api_base_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-latest"

    # Obsidian Engineering Memory (Obsidian Local REST API)
    obsidian_api_url: str = "https://127.0.0.1:27124"
    obsidian_api_key: str = ""
    obsidian_vault_subpath: str = "Hawk/investigations"

    # Task Execution Bounds
    task_timeout_seconds: int = 300
    max_retries: int = 3

    # CORS
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
