"""
app/__init__.py — Flask application factory.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from flask import Flask
from src.database import init_db


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = os.getenv('SECRET_KEY', 'jobhunter-dev-secret')

    # Init DB on startup
    with app.app_context():
        init_db()

    # Register blueprints
    from app.routes import main
    app.register_blueprint(main)

    # Start background scheduler
    from src.scheduler import start as start_scheduler
    start_scheduler()

    return app
