"""Configuration management for Azad MCP Server."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # VeriCase API Configuration
    api_base_url: str = field(
        default_factory=lambda: os.getenv("VERICASE_API_URL", "http://localhost:8010")
    )
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("VERICASE_API_KEY"))
    jwt_token: Optional[str] = field(
        default_factory=lambda: os.getenv("VERICASE_JWT_TOKEN")
    )

    # Authentication
    username: Optional[str] = field(
        default_factory=lambda: os.getenv("VERICASE_USERNAME")
    )
    password: Optional[str] = field(
        default_factory=lambda: os.getenv("VERICASE_PASSWORD")
    )

    # Request Configuration
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "30"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "3"))
    )

    # Feature Flags
    enable_ai_tools: bool = field(
        default_factory=lambda: os.getenv("ENABLE_AI_TOOLS", "true").lower() == "true"
    )
    enable_pst_tools: bool = field(
        default_factory=lambda: os.getenv("ENABLE_PST_TOOLS", "true").lower() == "true"
    )

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    @property
    def auth_header(self) -> dict:
        """Get authentication header for API requests."""
        if self.jwt_token:
            return {"Authorization": f"Bearer {self.jwt_token}"}
        if self.api_key:
            return {"X-API-Key": self.api_key}
        return {}


# Global settings instance
settings = Settings()
