import logging
import traceback

from functools import wraps


class TommyResponse:
    @staticmethod
    def success(data=None, message="Successful request.", status_code=200, code=None):
        response = {
            "status": "success",
            "message": message,
            "data": data if data else {}
        }
        if code:
            response["code"] = code
        return response, status_code

    @staticmethod
    def error(message, error_type=None, status_code=400, code=None):
        response = {
            "status": "error",
            "message": message
        }
        if error_type:
            response["error"] = error_type
        if code:
            response["code"] = code
        return response, status_code


class TommyErrors:

    @staticmethod
    def not_found(resource="Resource", message=None, code=None):
        if message is None:
            message = f"{resource} does not exist. Please ensure you're using the correct URL, endpoint, and parameters."
        return TommyResponse.error(
            message=message,
            error_type="NotFoundError",
            status_code=404,
            code=code
        )

    @staticmethod
    def bad_request(message=None, status_code=400, code=None):
        if message is None:
            message = f"Invalid formatting. Please ensure you're using the schema."
        return TommyResponse.error(
            message=message,
            error_type="BadRequestError",
            status_code=status_code,
            code=code
        )

    @staticmethod
    def unauthorized(message=None, code=None):
        if message is None:
            message = f"Authentication required. Please provider your access or refresh token for this operation."
        return TommyResponse.error(
            message=message,
            error_type="UnauthorizedError",
            status_code=401,
            code=code
        )

    @staticmethod
    def forbidden(message="Access forbidden", code=None):
        return TommyResponse.error(
            message=message,
            error_type="ForbiddenError",
            status_code=403,
            code=code
        )

    @staticmethod
    def validation_error(message="Validation failed", code=None):
        return TommyResponse.error(
            message=message,
            error_type="ValidationError",
            status_code=400,
            code=code
        )

    @staticmethod
    def too_many_requests_error(message="Too many requests.", code=None):
        return TommyResponse.error(
            message=message,
            error_type="TooManyRequestsError",
            status_code=429,
            code=code
        )

    @staticmethod
    def server_error(message="An unexpected error occurred", error=None, code=None):
        if error:
            logging.error("Full error stack:\n%s",
                          ''.join(traceback.format_exception(type(error), error, error.__traceback__)))
        else:
            logging.error("Full error stack:\n%s", traceback.format_exc())

        return TommyResponse.error(
            message=message,
            error_type="InternalError",
            status_code=500,
            code=code
        )

    @staticmethod
    def unprocessable_entity(message=None, code=None):
        if message is None:
            message = "The request was well-formed but contains invalid elements. One or more provided links are invalid."
        return TommyResponse.error(
            message=message,
            error_type="UnprocessableEntityError",
            status_code=422,
            code=code
        )

    @staticmethod
    def gone(message=None, code=None):
        if message is None:
            message = "The requested resource is no longer available and will not be available again."
        return TommyResponse.error(
            message=message,
            error_type="GoneError",
            status_code=410,
            code=code
        )


def handle_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            return TommyErrors.validation_error(str(e), code="VALIDATION_FAILED")
        except KeyError as e:
            return TommyErrors.bad_request(f"Missing required field: {str(e)}", code="MISSING_FIELD")
        except Exception as e:
            return TommyErrors.server_error(error=e, code="UNEXPECTED_ERROR")

    return wrapper