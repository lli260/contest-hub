# -*- coding: utf-8 -*-
"""Contest Hub 应用工厂。"""
import os

from flask import Flask

from . import db as db_module
from .config import (CACHE_TTL_SECONDS, DEFAULT_DB_PATH, DISABLE_BG_SYNC,
                     STATIC_DIR, STALE_DAYS, SYNC_INITIAL_DELAY,
                     SYNC_INTERVAL_HOURS, TEMPLATES_DIR)
from .routes import bp
from .sync import start_background_sync

__all__ = ["create_app"]

__version__ = "0.2.0"


def create_app(config=None):
    app = Flask(
        __name__,
        template_folder=TEMPLATES_DIR,
        static_folder=STATIC_DIR,
        static_url_path="/static",
    )
    app.secret_key = os.environ.get("CONTESTHUB_SECRET", "contest-hub-secret")
    app.config.update(
        DATABASE=DEFAULT_DB_PATH,
        DISABLE_BG_SYNC=DISABLE_BG_SYNC,
        SYNC_INTERVAL_HOURS=SYNC_INTERVAL_HOURS,
        SYNC_INITIAL_DELAY=SYNC_INITIAL_DELAY,
        CACHE_TTL_SECONDS=CACHE_TTL_SECONDS,
        STALE_DAYS=STALE_DAYS,
        JSON_AS_ASCII=False,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)

    db_module.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db_module.close_db)
    app.register_blueprint(bp)
    start_background_sync(app)
    return app
