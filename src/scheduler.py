"""
scheduler.py — background auto-refresh using APScheduler.
Runs pipeline + social scraper every N hours automatically.

Starts with the Flask app (called from app/__init__.py).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

# ── Config ───────────────────────────────────────────────────────────────────
REFRESH_HOURS    = int(os.getenv('REFRESH_HOURS', 6))
SEARCH_KEYWORDS  = ['data scientist', 'machine learning', 'data analyst', 'nlp engineer', 'intern data']
COUNTRIES        = ['gb', 'us', 'ae']
PAGES_PER_RUN    = 3   # 150 jobs per keyword per country per run

_scheduler = None
_last_run_time = None


def _refresh_job():
    global _last_run_time
    from datetime import datetime
    print(f'[Scheduler] Starting refresh at {datetime.now().isoformat()}')

    try:
        from pipeline import run as pipeline_run
        for country in COUNTRIES:
            for keyword in SEARCH_KEYWORDS[:3]:   # limit to avoid rate limits
                pipeline_run(keyword, country, PAGES_PER_RUN)
    except Exception as e:
        print(f'[Scheduler] pipeline error: {e}')

    try:
        from etl import run_etl
        run_etl()
    except Exception as e:
        print(f'[Scheduler] etl error: {e}')

    try:
        from social_scraper import run as social_run
        social_run(SEARCH_KEYWORDS)
    except Exception as e:
        print(f'[Scheduler] social scraper error: {e}')

    # Week 3: update seniority for new jobs
    try:
        from salary_model import update_job_seniority, train_salary_models
        update_job_seniority()
    except Exception as e:
        print(f'[Scheduler] seniority update error: {e}')

    # Week 3: retrain salary model if enough new salary data
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM jobs WHERE salary_min IS NOT NULL')
        salary_count = c.fetchone()[0]
        conn.close()
        if salary_count >= 50:
            train_salary_models()
    except Exception as e:
        print(f'[Scheduler] salary retrain error: {e}')

    _last_run_time = datetime.now().isoformat()
    print(f'[Scheduler] Refresh complete at {_last_run_time}')


def get_last_run() -> str | None:
    return _last_run_time


def start():
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=_refresh_job,
        trigger=IntervalTrigger(hours=REFRESH_HOURS),
        id='auto_refresh',
        name='JobHunter auto-refresh',
        replace_existing=True,
    )
    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False))
    print(f'[Scheduler] Started — refreshing every {REFRESH_HOURS}h.')


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print('[Scheduler] Stopped.')


def trigger_now():
    """Manually trigger a refresh (called from Flask route)."""
    import threading
    t = threading.Thread(target=_refresh_job, daemon=True)
    t.start()
    return 'Refresh started in background.'
