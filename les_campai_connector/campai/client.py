from typing import Generator, Unpack

import httpx
from httpx import Request, Response
from pydantic import RootModel

from .model import ResourceT, Organisation, Contact
from .params import GetListKwargs, build_page_params, build_filter_params


class CampaiAuth(httpx.Auth):
    def __init__(self, api_key: str):
        self.__api_key = api_key

    def auth_flow(self, request: httpx.Request) -> Generator[Request, Response, None]:
        request.headers["Authorization"] = self.__api_key
        yield request


class CampaiClient(object):
    def __init__(self, client: httpx.Client):
        self.__client = client

    def __get_resources(self, resource_type: type[ResourceT], *path: str, **params: Unpack[GetListKwargs]):
        page_params = params.get("page", None)
        filter_params = params.get("filter", None)
        request_params = build_page_params(page_params) | build_filter_params(filter_params)

        r = self.__client.get("/".join(path), params=request_params)
        assert r.status_code == httpx.codes.OK.value, "unexpected status code"

        list_resource_t = RootModel[list[resource_type]]
        return list_resource_t(r.json()).root

    def get_organisations(self, **params: Unpack[GetListKwargs]) -> list[Organisation]:
        return self.__get_resources(Organisation, "organisations", **params)

    def get_contacts(self, organisation: Organisation | str, **params: Unpack[GetListKwargs]) -> list[Contact]:
        organisation_id = organisation

        if isinstance(organisation, Organisation):
            organisation_id = organisation.id

        filter_params = params.get("filter", None) or {}
        params["filter"] = filter_params | {"organisation": organisation_id}

        return self.__get_resources(Contact, "contacts", **params)
