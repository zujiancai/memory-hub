"""Flask application factory."""
from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from .blob_storage import BlobStore, build_store_from_config
from .config import Config
from .db import init_engine, register_session_teardown
from .logging_utils import configure_logging


def create_app(
    config: Optional[Config] = None,
    blob_store: Optional[BlobStore] = None,
) -> Flask:
    load_dotenv(override=False)
    if config is None:
        config = Config.from_env()
    configure_logging()

    app = Flask(__name__, static_folder=None)
    _load_config(app, config)

    # Trust proxy for X-Forwarded-* if configured (helpful behind App Service).
    if config.trust_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_engine(config.database_url)
    register_session_teardown(app)

    store = blob_store or build_store_from_config(config)
    app.extensions["blob_store"] = store

    CORS(
        app,
        resources={r"/api/*": {"origins": config.cors_allowed_origins}},
        supports_credentials=True,
    )

    # Blueprints
    from .blueprints.root import bp as root_bp
    from .blueprints.user import bp as user_bp
    from .blueprints.asset import bp as asset_bp
    from .blueprints.storage import bp as storage_bp
    from .blueprints.trash import bp as trash_bp
    from .blueprints.admin import bp as admin_bp

    for bp in (root_bp, user_bp, asset_bp, storage_bp, trash_bp, admin_bp):
        app.register_blueprint(bp)

    # Serve SPA if the built assets directory exists
    ui_dir = app.config.get("UI_DIST_DIR")
    if ui_dir and os.path.isdir(ui_dir) and os.path.isfile(os.path.join(ui_dir, "index.html")):
        from .blueprints.spa import bp as spa_bp

        app.register_blueprint(spa_bp)

    _register_cli(app)
    _register_error_handlers(app)
    return app


def _load_config(app: Flask, config: Config) -> None:
    app.config["FLASK_SECRET"] = config.flask_secret
    app.config["SECRET_KEY"] = config.flask_secret
    app.config["JWT_SIGNING_KEY"] = config.jwt_signing_key
    app.config["JWT_ACCESS_TTL_SECONDS"] = config.jwt_access_ttl_seconds
    app.config["JWT_REFRESH_TTL_SECONDS"] = config.jwt_refresh_ttl_seconds
    app.config["TRASH_SESSION_TTL_SECONDS"] = config.trash_session_ttl_seconds
    app.config["DEFAULT_USER_QUOTA_BYTES"] = config.default_user_quota_bytes
    app.config["MAX_AVATAR_BYTES"] = config.max_avatar_bytes
    app.config["TRASH_GRACE_DAYS"] = config.trash_grace_days
    app.config["GOOGLE_CLIENT_ID"] = config.google_client_id
    app.config["GOOGLE_CLIENT_SECRET"] = config.google_client_secret
    app.config["GOOGLE_REDIRECT_URI"] = config.google_redirect_uri
    app.config["AZURE_STORAGE_CONTAINER"] = config.azure_storage_container
    app.config["GIT_SHA"] = config.git_sha
    app.config["UI_DIST_DIR"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "dist"
    )


def _register_cli(app: Flask) -> None:
    import click

    from .cli import cleanup_command, seed_dev_user_command, worker_drain_command

    app.cli.add_command(cleanup_command)
    app.cli.add_command(seed_dev_user_command)
    app.cli.add_command(worker_drain_command)

    @app.cli.command("db-init")
    def db_init():
        """Create all Phase 1 tables (use for tests / quick bootstrap)."""
        from .db import get_engine
        from .models import Base as ModelBase

        ModelBase.metadata.create_all(get_engine())
        click.echo("tables created")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def _404(_e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def _500(_e):
        return jsonify({"error": "internal error"}), 500
