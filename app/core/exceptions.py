"""统一错误码与异常。接口永远返回同一种错误结构。"""


class AppError(Exception):
    """所有业务异常的基类。"""

    code = "internal_error"
    status = 500
    message = "服务内部错误"

    def __init__(self, message: str = "", **ctx):
        self.message = message or self.message
        self.ctx = ctx
        super().__init__(self.message)

    def to_dict(self, trace_id: str = "") -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "trace_id": trace_id,
                **({"context": self.ctx} if self.ctx else {}),
            }
        }


class ValidationError(AppError):
    code = "invalid_request"
    status = 400
    message = "请求参数不合法"


class NotFoundError(AppError):
    code = "not_found"
    status = 404
    message = "资源不存在"


class UnauthorizedError(AppError):
    code = "unauthorized"
    status = 401
    message = "缺少或错误的 API Key"


class RateLimitedError(AppError):
    code = "rate_limited"
    status = 429
    message = "请求过于频繁"


class UpstreamError(AppError):
    """模型或数据库等上游不可用。"""

    code = "upstream_unavailable"
    status = 503
    message = "上游服务不可用"
