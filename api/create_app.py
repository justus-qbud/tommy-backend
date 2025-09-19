import os
import uuid

from dotenv import load_dotenv
from flask import Flask, make_response
from flask_cors import CORS
from flask_limiter.errors import RateLimitExceeded
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BaseConverter, ValidationError

from api.common.limiter import LIMITER
from api.common.response import TommyErrors
from api.resources import api


class UUIDConverter(BaseConverter):
    def to_python(self, value):
        try:
            return str(uuid.UUID(value))
        except ValueError:
            raise ValidationError("Not a valid UUID.")

    def to_url(self, value):
        return str(value)


def create_app():
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_pyfile("config.py")
    app.secret_key = os.getenv("JWT_SECRET_KEY")
    app.url_map.converters["uuid"] = UUIDConverter

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    cors = CORS()
    cors.init_app(app, supports_credentials=True)

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit_exceeded(error):
        return TommyErrors.too_many_requests_error(message="Rate limit exceeded. Please try again later.")

    @app.errorhandler(Exception)
    def handle_exception(error):
        return TommyErrors.server_error(error=error)

    api.init_app(app)

    # fix IP source information
    app.config["PREFERRED_URL_SCHEME"] = "https"
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    LIMITER.init_app(app)

    return app