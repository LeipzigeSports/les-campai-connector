import json
from typing import Annotated

from keycloak import KeycloakAdmin
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, EmailStr, UUID4, RootModel
from pydantic.alias_generators import to_camel


ATTRIBUTE_CAMPAI_ID = "campai-id"
NO_MEMBER_SUFFIX = "_nomember"


class MinimalUserRepresentation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool
    username: str
    id: UUID4
    email: EmailStr | None = None
    email_verified: bool
    attributes: Annotated[dict[str, list[str]], Field(default_factory=dict)]
    groups: Annotated[list[str], Field(default_factory=list)]


class MinimalUpdateUserRepresentation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool | None = None
    username: str | None = None
    email: EmailStr | None = None
    email_verified: bool | None = None
    attributes: dict[str, list[str]] | None = None


class MinimalGroupRepresentation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)
    id: UUID4
    name: str


def _find_user_by_query(kc_admin: KeycloakAdmin, query: dict) -> dict | None:
    users = kc_admin.get_users(query)

    if len(users) != 1:
        if len(users) > 1:
            logger.warning(f"Query {json.dumps(query)} returned more than one result while expecting to get at most one")

        return None

    return users.pop()


def find_user_by_campai_id(kc_admin: KeycloakAdmin, campai_id: str) -> dict | None:
    return _find_user_by_query(kc_admin, {"q": f"{ATTRIBUTE_CAMPAI_ID}:{campai_id}"})


def find_user_by_email(kc_admin: KeycloakAdmin, email: str) -> dict | None:
    return _find_user_by_query(kc_admin, {"email": email})


def find_group_by_name(kc_admin: KeycloakAdmin, name: str) -> dict | None:
    groups = kc_admin.get_groups(query={"search": name})

    if len(groups) != 1:
        return None

    return groups.pop()


def must_parse_into_user(value: dict) -> MinimalUserRepresentation:
    return MinimalUserRepresentation.model_validate(value)


def must_parse_into_group(value: dict) -> MinimalGroupRepresentation:
    return MinimalGroupRepresentation.model_validate(value)


def must_parse_into_groups(value: list[dict]) -> list[MinimalGroupRepresentation]:
    return RootModel[list[MinimalGroupRepresentation]].model_validate(value).root
