"""Auth0 configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class AuthConfig(BaseSettings):
    auth_enabled: bool = False
    auth0_domain: str = ""
    auth0_api_audience: str = ""
    auth0_algorithms: list[str] = ["RS256"]

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    @property
    def issuer(self) -> str:
        return f"https://{self.auth0_domain}/"

    @property
    def jwks_uri(self) -> str:
        return f"https://{self.auth0_domain}/.well-known/jwks.json"


@lru_cache
def get_auth_config() -> AuthConfig:
    return AuthConfig()
