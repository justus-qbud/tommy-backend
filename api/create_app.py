import os
import uuid
from jwt.exceptions import PyJWTError

from dotenv import load_dotenv
from flask import Flask, make_response, request
from flask_cors import CORS
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BaseConverter, ValidationError

from api.common.access import rebuild_user_access
from api.common.auth import Auth
from api.common.db import Database
from api.common.exceptions import ArchivedError
from api.common.limiter import LIMITER
from api.common.logging import configure_logging
from api.common.openapi import document_api, generate_openapi_spec, setup_openapi
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
    app.config.from_pyfile('config.py')
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
    app.config["result_backend"] = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    app.config["broker_url"] = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    app.secret_key = os.getenv("JWT_SECRET_KEY")

    # enforce UUID url parameters
    app.url_map.converters["uuid"] = UUIDConverter

    jwt = JWTManager(app)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    Database.init_app(app)

    cors = CORS()
    cors.init_app(app, supports_credentials=True)

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit_exceeded(error):
        return TommyErrors.too_many_requests_error(message="Rate limit exceeded. Please try again later.")

    @app.errorhandler(ArchivedError)
    def handle_gone(e):
        body, status = TommyErrors.gone()
        resp = make_response(body, status)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    @app.errorhandler(Exception)
    def handle_exception(error):
        return TommyErrors.server_error(error=error)

    @jwt.invalid_token_loader
    def invalid_token(jwt_header, jwt_payload):
        return TommyErrors.not_found()

    @jwt.unauthorized_loader
    def unauthorized_token(reason: str):
        return TommyErrors.unauthorized()


    api.init_app(app)

    configure_logging(app, log_level="INFO", exclude_paths=["/logs", "/health"], log_dir="logs")

    if app.config["FLASK_ENV"] == "development":
        openapi_path_private = os.path.join(app.instance_path, "qbud_swagger_private.json")
        openapi_path_public = os.path.join(app.instance_path, "qbud_swagger_public.json")
        private_spec, public_spec = generate_openapi_spec(app, openapi_path_private, openapi_path_public)
        setup_openapi(app, private_spec, public_spec)

    # fix IP source information
    app.config["PREFERRED_URL_SCHEME"] = "https"
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1
    )

    LIMITER.init_app(app)

    return app