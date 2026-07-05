"""
app/__init__.py — Flask application factory.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from flask import Flask, render_template
from src.database import init_db


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = os.getenv('SECRET_KEY') or os.urandom(32).hex()
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB upload limit

    # Download database from HF Hub if available
    try:
        from hf_sync import download_db_from_hf
        download_db_from_hf()
    except Exception as e:
        import logging
        logging.warning(f"[HF-Sync] Warning downloading DB on startup: {e}")

    # Init DB on startup
    with app.app_context():
        init_db()

    # Register blueprints
    from app.routes import main
    app.register_blueprint(main)

    # Start background scheduler
    from src.scheduler import start as start_scheduler
    start_scheduler()

    # Preload SentenceTransformer model and Chroma client in a background daemon thread
    import threading
    import logging
    def preload_resources():
        try:
            # Trigger startup dataset creation and database sync to HF
            try:
                from hf_sync import upload_db_to_hf
                upload_db_to_hf()
            except Exception as upload_err:
                logging.warning(f"[HF-Sync] Startup database upload skipped/failed: {upload_err}")

            logging.info("[RAG] Background preloading embedding model and ChromaDB client...")
            from src.rag_assistant import _get_embedding_model, get_chroma_client_and_collection, index_new_jobs
            _get_embedding_model()
            get_chroma_client_and_collection()
            # Index downloaded/restored jobs into ChromaDB in background
            index_new_jobs()
            logging.info("[RAG] Background preloading and indexing complete!")
        except Exception as e:
            logging.warning(f"[RAG] Warning preloading resources in background: {e}")

    threading.Thread(target=preload_resources, daemon=True).start()

    # Translations Template Context Processor
    @app.context_processor
    def inject_translations():
        from flask import session
        from app.translations import TRANSLATIONS
        lang = session.get('lang', 'en')
        def translate(key):
            return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)

        def days_ago(date_str):
            if not date_str:
                return ""
            try:
                clean_date = date_str[:10]
                from datetime import datetime
                d = datetime.strptime(clean_date, "%Y-%m-%d")
                delta = datetime.now() - d
                days = delta.days
                if days < 0:
                    days = 0
                if lang == 'ar':
                    if days == 0:
                        return "النهاردة"
                    elif days == 1:
                        return "إمبارح"
                    elif days == 2:
                        return "من يومين"
                    elif 3 <= days <= 10:
                        return f"من {days} أيام"
                    else:
                        return f"من {days} يوم"
                else:
                    if days == 0:
                        return "today"
                    elif days == 1:
                        return "yesterday"
                    else:
                        return f"{days} days ago"
            except Exception:
                return ""

        return dict(t=translate, current_lang=lang, days_ago=days_ago)

    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('500.html'), 500

    return app
