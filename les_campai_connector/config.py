from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeycloakConfig(BaseModel):
    client_id: str
    client_secret: SecretStr
    url: str
    realm_name: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__")
    keycloak: KeycloakConfig
