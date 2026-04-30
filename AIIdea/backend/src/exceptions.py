"""Project-wide error codes and the APIError exception.

Error code scheme: `<module>001..999`, kept centralized here per backend
coding standards. The envelope shape `{code, message, data, request_id}`
is applied in `src.envelope`.
"""

from __future__ import annotations


class ErrorCode:
    SUCCESS = "000000"
    INTERNAL = "999999"
    BAD_REQUEST = "400000"
    NOT_FOUND = "404000"
    METHOD_NOT_ALLOWED = "405000"
    SERVICE_UNAVAILABLE = "503000"

    SOURCE_ITEM_NOT_FOUND = "SRC001"
    SOURCE_ITEM_BAD_ID = "SRC002"

    ANALYSIS_NOT_FOUND = "ANA001"
    ANALYSIS_BAD_ID = "ANA002"

    UNKNOWN_JOB = "PIPELINE001"
    JOB_ALREADY_RUNNING = "PIPELINE002"
    SCHEDULER_DOWN = "PIPELINE003"

    STATS_UNAVAILABLE = "STATS001"
    HEALTH_DB_FAIL = "HEALTH001"

    PRODUCT_EXPERIENCE_NOT_FOUND = "PEX001"
    PRODUCT_EXPERIENCE_BAD_ID = "PEX002"
    PRODUCT_EXPERIENCE_URL_INVALID = "PEX003"


class APIError(Exception):
    """Raise inside a handler to produce a structured error response.

    ``http_status`` controls the HTTP code the client receives; ``code`` is
    the stable business-level identifier surfaced in the JSON envelope.
    """

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        data: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data
