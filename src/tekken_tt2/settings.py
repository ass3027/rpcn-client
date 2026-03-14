from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rpcn_user: str
    rpcn_password: str
    rpcn_token: str = ""
    rpcn_host: str = "np.rpcs3.net"
    rpcn_port: int = 31313

    redis_url: str = "redis://localhost:6379"
    cache_ttl_servers: int = 3600
    cache_ttl_leaderboard: int = 300
    cache_ttl_rooms: int = 60
    cache_ttl_rooms_all: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
