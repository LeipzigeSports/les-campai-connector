from datetime import datetime
from typing import Annotated, TypeVar, Literal, Any

from pydantic import ConfigDict, BaseModel, Field, EmailStr, BeforeValidator
from pydantic.alias_generators import to_camel

ResourceT = TypeVar("ResourceT", bound="BaseModel")


def convert_empty_str_to_none(v: str) -> str | None:
    return None if v == "" else v


class CampaiBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)


class IdMixin(BaseModel):
    id: Annotated[str, Field(alias="_id")]


class MetadataMixin(BaseModel):
    created_at: datetime
    updated_at: datetime


class Organisation(CampaiBaseModel, IdMixin, MetadataMixin):
    merge_tags: dict[str, Any]
    name: str


ContactMembershipStatus = Literal["hasLeft", "willLeave", "isActive", "willEnter"]


class ContactPersonal(CampaiBaseModel):
    is_person: bool
    is_organisation: bool
    person_first_name: str
    person_last_name: str


class ContactCommunication(CampaiBaseModel):
    email: Annotated[EmailStr | None, BeforeValidator(convert_empty_str_to_none)]


class ContactMembership(CampaiBaseModel):
    enter_date: datetime | None
    leave_date: datetime | None
    termination_date: datetime | None
    status: ContactMembershipStatus | None


class Contact(CampaiBaseModel, IdMixin, MetadataMixin):
    merge_tags: dict[str, Any]
    personal: ContactPersonal
    membership: ContactMembership
    communication: ContactCommunication
