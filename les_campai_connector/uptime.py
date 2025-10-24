import httpx
from pydantic import BaseModel


class OkResponse(BaseModel):
    ok: bool


class ErrorResponse(BaseModel):
    ok: bool
    msg: str


def check_response(resp: httpx.Response):
    if resp.status_code == httpx.codes.OK.value:
        response = OkResponse(**resp.json())

        if not response.ok:
            raise ValueError("uptime endpoint returned a 200, but response content indicates an error")

        return

    if resp.status_code == httpx.codes.NOT_FOUND.value:
        response = ErrorResponse(**resp.json())

        if response.ok:
            raise ValueError("uptime endpoint returned a 404, but response content indicates success")

        raise ValueError(f"uptime endpoint returned a 404: {response.msg}")

    raise ValueError(f"uptime endpoint returned unexpected status code {resp.status_code}")


class UptimeKumaClient(object):
    def __init__(self, uptime_endpoint_url: str):
        self.__uptime_endpoint_url = uptime_endpoint_url
        self.__client = httpx.Client()

    def up(self, message="OK"):
        check_response(self.__client.get(self.__uptime_endpoint_url, params={"status": "up", "msg": message}))

    def down(self, message="Failed"):
        check_response(self.__client.get(self.__uptime_endpoint_url, params={"status": "down", "msg": message}))
