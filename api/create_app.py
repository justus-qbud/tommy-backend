import os
import uuid
from jwt.exceptions import PyJWTError

from dotenv import load_dotenv
from flask import Flask, make_response, request
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required, JWTManager, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException, NoAuthorizationError
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
from api.common.response import QBudErrors
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
    app.url_map.converters['uuid'] = UUIDConverter

    jwt = JWTManager(app)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    Database.init_app(app)

    cors = CORS()
    cors.init_app(app, supports_credentials=True)

    @app.route("/auth/token", methods=["POST"])
    @document_api(
        summary="Developer auth resource",
        description="Provides a fresh `access_token` and a `refresh_token` to authorized users. Uses Basic auth scheme.",
        public=True,
        requires_auth=True,
        responses={
            200: "Success",
            400: "BadRequest",
            422: "ValidationError"
        },
        response_examples={
            200: {
                "access_token": "foo",
                "refresh_token": "bar",
                "access_token_expires": 900,
                "refresh_token_expires": 2592000,
            }
        },
        auth_scheme="BasicAuth"
    )
    @LIMITER.limit("15 per minute", key_func=get_remote_address)
    def handle_token():
        auth_header = request.headers.get("Authorization")
        if auth_header and isinstance(auth_header, str):
            return Auth.login_client(authorization_header=auth_header)
        return QBudErrors.bad_request(message="Invalid Authorization header")

    @app.route("/auth/login", methods=["POST"])
    @LIMITER.limit("15 per minute", key_func=get_remote_address)
    def handle_login():
        return Auth.login(request.json)

    @app.route("/auth/refresh", methods=["POST"])
    @document_api(
        summary="Auth refresh resource",
        description="Provides a non-fresh `access_token` and a `refresh_token` to authorized users.",
        public=True,
        requires_auth=True,
        responses={
            200: "Success",
            400: "BadRequest",
            422: "ValidationError"
        },
        response_examples={
            200: {
                "access_token": "foo",
                "refresh_token": "bar",
                "access_token_expires": 900,
                "refresh_token_expires": 2592000,
            }
        }
    )
    @jwt_required(refresh=True)
    @LIMITER.limit("5 per minute", key_func=get_jwt_identity)
    def refresh():
        return Auth.refresh_token()

    @app.route("/auth/logout", methods=["POST"])
    @LIMITER.limit("15 per minute", key_func=get_remote_address)
    def logout():
        response = Auth.get_token_response("", "", logout=True)
        return response, 200

    @app.route("/api/v1/user/auth_token", methods=["GET"])
    @jwt_required()
    @LIMITER.limit("5 per minute", key_func=get_jwt_identity)
    def generate_token():
        return Auth.generate_client_id_and_secret()

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return QBudErrors.unauthorized()

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return QBudErrors.unauthorized()

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return QBudErrors.unauthorized()

    @app.errorhandler(JWTExtendedException)
    @app.errorhandler(NoAuthorizationError)
    @app.errorhandler(PyJWTError)
    def handle_jwt_exceptions(error):
        return QBudErrors.unauthorized()

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit_exceeded(error):
        return QBudErrors.too_many_requests_error(message="Rate limit exceeded. Please try again later.")

    @app.errorhandler(ArchivedError)
    def handle_gone(e):
        body, status = QBudErrors.gone()
        resp = make_response(body, status)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    @app.errorhandler(Exception)
    def handle_exception(error):
        return QBudErrors.server_error(error=error)

    @jwt.invalid_token_loader
    def invalid_token(jwt_header, jwt_payload):
        return QBudErrors.not_found()

    @jwt.unauthorized_loader
    def unauthorized_token(reason: str):
        return QBudErrors.unauthorized()


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