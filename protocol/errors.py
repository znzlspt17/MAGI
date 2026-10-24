"""전송 방식과 무관한 공개 오류 코드."""

HTTP_STATUS = {
    "not_found": 404,
    "invalid": 400,
    "conflict": 409,
    "busy": 409,
    "capacity": 503,
    "quota": 429,
    "unauthorized": 401,
    "forbidden": 403,
    "configuration": 503,
    "unavailable": 503,
    "translation_invalid": 502,
    "internal": 503,
}
UNCERTAIN_METHODS = {
    "job.command",
    "document",
    "cleanup.execute",
    "knowledge.impact.analyse",
}
REJECTED_CODES = {
    "not_found",
    "invalid",
    "conflict",
    "busy",
    "capacity",
    "quota",
    "unauthorized",
    "forbidden",
    "configuration",
}
