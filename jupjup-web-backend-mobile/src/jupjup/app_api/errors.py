"""Compatibility errors are deliberately independent of the /v1 envelope."""

from starlette.responses import JSONResponse


class ContractError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code

    def response(self) -> JSONResponse:
        return JSONResponse({"error": {"code": self.code, "message": "요청을 처리할 수 없습니다."}}, self.status)
