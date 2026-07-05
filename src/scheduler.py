"""
scheduler.py — background auto-refresh using APScheduler.
Runs pipeline + social scraper every N hours automatically.

Starts with the Flask app (called from app/__init__.py).
"""

import logging
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
    logging.info(f'[Scheduler] Starting refresh at {datetime.now().isoformat()}')

    try:
        from pipeline import run as pipeline_run
        for country in COUNTRIES:
            for keyword in SEARCH_KEYWORDS[:3]:   # limit to avoid rate limits
                pipeline_run(keyword, country, PAGES_PER_RUN)
    except Exception as e:
        logging.info(f'[Scheduler] pipeline error: {e}')

    try:
        from etl import run_etl
        run_etl()
    except Exception as e:
        logging.info(f'[Scheduler] etl error: {e}')

    try:
        import subprocess
        import sys
        script_path = os.path.join(os.path.dirname(__file__), 'social_scraper.py')
        logging.info(f'[Scheduler] Running social scraper as subprocess: {script_path}')
        subprocess.run(
            [sys.executable, '-u', script_path] + SEARCH_KEYWORDS,
            timeout=120,
            check=True
        )
    except subprocess.TimeoutExpired:
        logging.info('[Scheduler] Social scraper timed out after 120 seconds. Skipping.')
    except Exception as e:
        logging.info(f'[Scheduler] social scraper error: {e}')


    # Week 3: update seniority for new jobs
    try:
        from salary_model import update_job_seniority, train_salary_models
        update_job_seniority()
    except Exception as e:
        logging.info(f'[Scheduler] seniority update error: {e}')

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
        logging.info(f'[Scheduler] salary retrain error: {e}')

    # Week 4: Sync all new jobs into ChromaDB vector database
    try:
        from rag_assistant import index_new_jobs
        index_new_jobs()
    except Exception as e:
        logging.info(f'[Scheduler] ChromaDB indexing error: {e}')

    _last_run_time = datetime.now().isoformat()
    logging.info(f'[Scheduler] Refresh complete at {_last_run_time}')


def _auto_backfill_summaries_job():
    from datetime import datetime
    from rag_assistant import is_summary_backed_off, get_summary_backoff, summarize_description
    from database import get_connection, update_job_summaries
    import time
    
    if is_summary_backed_off():
        backoff_until = get_summary_backoff()
        logging.info(f"[Scheduler] AI Summary backfill is backed off until {backoff_until.isoformat() if backoff_until else 'unknown'}.")
        return

    logging.info(f"[Scheduler] Starting AI Summary backfill batch at {datetime.now().isoformat()}...")
    
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT id, description FROM jobs
            WHERE (summary_en IS NULL OR summary_ar IS NULL OR summary_en = '' OR summary_ar = '')
              AND description IS NOT NULL
              AND description != ''
              AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
            LIMIT 40
        ''')
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        logging.info(f"[Scheduler] Database error during backfill fetch: {e}")
        return

    if not rows:
        logging.info("[Scheduler] AI Summary backfill: No jobs need summaries. All caught up! 🎉")
        return

    logging.info(f"[Scheduler] Processing {len(rows)} jobs in this backfill batch.")
    success_count = 0
    
    for r in rows:
        if is_summary_backed_off():
            logging.info("[Scheduler] AI Summarization backed off during batch execution. Stopping batch.")
            break

        job_id = r['id']
        description = r['description']

        try:
            summary_en, summary_ar = summarize_description(description)
            if summary_en and summary_ar:
                update_job_summaries(job_id, summary_en, summary_ar)
                success_count += 1
                time.sleep(0.5)  # respect rate limits
            else:
                logging.info(f"[Scheduler] Empty summary returned for job ID {job_id}.")
        except Exception as e:
            err_str = str(e)
            if is_summary_backed_off():
                logging.info(f"[Scheduler] Daily limit reached while summarizing job ID {job_id}. Stopping batch.")
                break
            elif '429' in err_str or 'rate_limit' in err_str.lower():
                logging.info(f"[Scheduler] Minute rate limit hit for job ID {job_id}. Sleeping 30s before retrying...")
                time.sleep(30)
                try:
                    summary_en, summary_ar = summarize_description(description)
                    if summary_en and summary_ar:
                        update_job_summaries(job_id, summary_en, summary_ar)
                        success_count += 1
                except Exception as retry_err:
                    logging.info(f"[Scheduler] Retry failed for job ID {job_id}: {retry_err}")
            else:
                logging.info(f"[Scheduler] Error summarizing job ID {job_id} in background: {e}")

    logging.info(f"[Scheduler] AI Summary backfill batch finished. Summarized: {success_count}/{len(rows)} jobs.")


def get_last_run() -> str | None:
    return _last_run_time


def start():
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    from datetime import datetime

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=_refresh_job,
        trigger=IntervalTrigger(hours=REFRESH_HOURS),
        id='auto_refresh',
        name='JobHunter auto-refresh',
        replace_existing=True,
    )
    _scheduler.add_job(
        func=_auto_backfill_summaries_job,
        trigger=IntervalTrigger(minutes=15),
        id='auto_backfill_summaries',
        name='JobHunter AI summary backfill',
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False))
    logging.info(f'[Scheduler] Started — refreshing every {REFRESH_HOURS}h, summarizing every 15m.')



def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logging.info('[Scheduler] Stopped.')


def trigger_now():
    """Manually trigger a refresh (called from Flask route)."""
    import threading
    t = threading.Thread(target=_refresh_job, daemon=True)
    t.start()
    return 'Refresh started in background.'
