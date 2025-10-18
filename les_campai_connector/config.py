from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CampaiConfig(BaseModel):
    api_key: SecretStr
    base_url: str = "https://api.campai.com"


class KeycloakConfig(BaseModel):
    client_id: str
    client_secret: SecretStr
    url: str
    realm_name: str


class SyncConfig(BaseModel):
    organisation_name: str
    default_group_name: str
    auto_apply: bool


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__")
    keycloak: KeycloakConfig
    campai: CampaiConfig
    sync: SyncConfig
