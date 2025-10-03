from datetime import datetime
from typing import Annotated, TypeVar

from pydantic import ConfigDict, BaseModel, Field
from pydantic.alias_generators import to_camel

ResourceT = TypeVar("ResourceT", bound="BaseModel")


class Organisation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    id: Annotated[str, Field(alias="_id")]
    created_at: datetime
    updated_at: datetime
    merge_tags: dict[str, str]
    name: str
