from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Monicask"
    environment: str = "dev"
    database_url: str = "sqlite:///./monicask.db"

    ami_host: str = ""
    ami_port: int = 5038
    ami_username: str = ""
    ami_secret: str = ""
    ami_timeout: float = 5.0
    ami_max_attempts: int = 3
    ami_retry_backoff: float = 0.25
    managed_queues: list[str] = Field(default_factory=lambda: ["default"])

    zammad_base_url: str = ""
    zammad_token: str = ""
    zammad_timeout: float = 5.0
    final_ticket_status: str = "closed"
    webhook_secret: str = ""

    wrap_up_enabled: bool = False
    wrap_up_seconds: int = 30

    def ami_mode(self) -> str:
        return "real" if self.ami_host else "mock"

    def zammad_mode(self) -> str:
        return "real" if self.zammad_base_url else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
