"""
PlastiTrack Flask application.

Run from the project root (the folder that contains index.html):

    python -m backend.app

Then open http://127.0.0.1:5000/ for the original frontend (served
unchanged) and http://127.0.0.1:5000/api/health for the API.
"""

import logging
import os
import sqlite3

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from . import database
from .calculations import DATASET_VERSION
from .errors import ConflictError, NotFoundError, ValidationError
from .routes import campus, challenges, footprint, history, passport

API_VERSION = "1.0"

# Only these files from the project root are served. This keeps the
# database, backend code and .git folder private while letting the
# original frontend run from the same local server without modification.
FRONTEND_FILES = {"index.html", "style.css", "script.js",
                  "api.js", "integration.js", "integration.css"}


def create_app(config=None):
    # static_folder=None: we serve the frontend through an explicit
    # allow-list instead of exposing a whole folder.
    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATABASE=os.environ.get("PLASTITRACK_DB", database.DEFAULT_DB_PATH),
        # Every legitimate request body is well under 1 KB; anything bigger
        # than 64 KB is rejected with 413 before it is parsed.
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.json.sort_keys = False
    if config:
        app.config.update(config)

    database.init_app(app)
    for module in (footprint, history, challenges, passport, campus):
        app.register_blueprint(module.bp)
    _register_error_handlers(app)
    _register_frontend(app)

    @app.get("/api/health")
    def health():
        try:
            found = {r[0] for r in database.get_db().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            db_status = ("ok" if database.REQUIRED_TABLES <= found
                         else "missing_tables")
        except Exception:  # pragma: no cover - only if the file is broken
            app.logger.exception("Database health check failed")
            db_status = "error"
        status = 200 if db_status == "ok" else 503
        return jsonify({"status": "ok" if status == 200 else "degraded",
                        "database": db_status, "api_version": API_VERSION,
                        "dataset_version": DATASET_VERSION}), status

    return app


def _error(status, message, details=None):
    body = {"error": message, "status": status}
    if details:
        body["details"] = details
    return jsonify(body), status


def _register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def handle_validation(exc):
        return _error(400, exc.message, exc.errors)

    @app.errorhandler(NotFoundError)
    def handle_not_found(exc):
        return _error(404, exc.message)

    @app.errorhandler(ConflictError)
    def handle_conflict(exc):
        return _error(409, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return _error(exc.code, exc.description)

    # Safety nets. The services already prevent these, but if a database
    # constraint is ever hit the client gets a clear JSON answer, not a 500.
    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity(exc):
        app.logger.warning("Integrity error: %s", exc)
        return _error(409, "The request conflicts with existing data.")

    @app.errorhandler(sqlite3.OperationalError)
    def handle_operational(exc):
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return _error(503, "The database is busy. Please try again.")
        app.logger.exception("Database error")
        return _error(500, "Internal server error.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error")
        return _error(500, "Internal server error.")


def _register_frontend(app):
    root = database.PROJECT_ROOT

    def make_view(filename):
        def view():
            return send_from_directory(root, filename)
        view.__name__ = "frontend_" + filename.replace(".", "_")
        return view

    # One explicit route per file (no catch-all), so unknown paths are a
    # 404 and wrong methods on /api routes are still a proper 405.
    app.add_url_rule("/", "frontend_root", make_view("index.html"),
                     methods=["GET"])
    for name in sorted(FRONTEND_FILES):
        app.add_url_rule("/" + name, view_func=make_view(name),
                         methods=["GET"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    print("PlastiTrack running at http://127.0.0.1:5000/")
    print("Database:", application.config["DATABASE"])
    # 127.0.0.1 = only reachable from this laptop.
    application.run(host="127.0.0.1", port=5000,
                    debug=os.environ.get("FLASK_DEBUG") == "1")
