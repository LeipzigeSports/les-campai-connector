from typing import TypedDict

DEFAULT_PAGE_LIMIT = 50
DEFAULT_PAGE_SKIP = 0

# https://docs2.campai.com/queryLanguage
FilterParams = dict[str, str]


class PageParams(TypedDict, total=False):
    limit: int
    skip: int


class GetListKwargs(TypedDict, total=False):
    filter: FilterParams | None
    page: PageParams | None


def build_page_params(params: PageParams | None):
    if params is None:
        params = {}

    return {"limit": params.get("limit", DEFAULT_PAGE_LIMIT), "skip": params.get("skip", DEFAULT_PAGE_SKIP)}


def build_filter_params(params: FilterParams | None):
    return params or {}
