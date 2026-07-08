"""
app/routes.py — all Flask URL routes.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import math
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify

from database import (
    fetch_all_jobs, get_stats, get_filter_options,
    get_seniority_breakdown, get_avg_salary_by_seniority,
)
try:
    from recommender import recommend, get_top_skills, get_salary_stats
except Exception:
    import pandas as pd
    def recommend(*args, **kwargs):
        return pd.DataFrame()
    def get_top_skills(*args, **kwargs):
        return []
    def get_salary_stats(*args, **kwargs):
        return pd.DataFrame()

from scheduler import get_last_run, trigger_now

try:
    from nlp_analysis import contract_type_breakdown
except Exception:
    def contract_type_breakdown():
        return []

try:
    from salary_model import predict_salary
except Exception:
    def predict_salary(*args, **kwargs):
        return {}

try:
    from rag_assistant import chat_with_coach
except Exception:
    def chat_with_coach(*args, **kwargs):
        return "Service temporarily unavailable."

main = Blueprint('main', __name__)


def _enrich_salaries(jobs_list):
    """Predict salaries for jobs missing salary data (in-place)."""
    for j in jobs_list:
        s_min = j.get('salary_min')
        s_max = j.get('salary_max')
        if isinstance(s_min, float) and math.isnan(s_min):
            s_min = None
            j['salary_min'] = None
        elif isinstance(s_min, str) and not s_min.strip():
            s_min = None
            j['salary_min'] = None
            
        if isinstance(s_max, float) and math.isnan(s_max):
            s_max = None
            j['salary_max'] = None
        elif isinstance(s_max, str) and not s_max.strip():
            s_max = None
            j['salary_max'] = None

        if s_min is None or s_max is None:
            pred = predict_salary(
                j.get('title', ''),
                j.get('description', ''),
                j.get('country', ''),
                j.get('job_type', 'onsite'),
                j.get('contract_type', 'full-time')
            )
            if pred.get('salary_min') is not None:
                j['predicted_min'] = pred['salary_min']
                j['predicted_max'] = pred['salary_max']
                j['predicted_period'] = pred.get('period', 'annual')


# ── Dashboard ────────────────────────────────────────────────────────────────
@main.route('/')
def index():
    stats       = get_stats()
    top_skills  = get_top_skills(10)
    if hasattr(top_skills, 'to_dict'):
        top_skills = top_skills.to_dict(orient='records')

    # contract type breakdown
    contract_breakdown = contract_type_breakdown()

    # Top countries
    from database import get_connection
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT country, COUNT(*) as cnt
        FROM jobs
        WHERE country IS NOT NULL AND country != ''
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        GROUP BY country ORDER BY cnt DESC LIMIT 6
    """)
    top_countries = [dict(r) for r in c.fetchall()]
    conn.close()

    last_run = get_last_run()

    return render_template(
        'index.html',
        stats=stats,
        top_skills=top_skills,
        contract_breakdown=contract_breakdown,
        top_countries=top_countries,
        last_run=last_run,
    )



# ── Jobs list ────────────────────────────────────────────────────────────────
@main.route('/jobs')
def jobs():
    country       = request.args.get('country', 'all')
    job_type      = request.args.get('job_type', 'all')
    contract_type = request.args.get('contract_type', 'all')
    seniority     = request.args.get('seniority', 'all')
    search        = request.args.get('q', '').strip().lower()
    sort          = request.args.get('sort', 'newest')
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1

    all_jobs, sort_intent = fetch_all_jobs(
        country=country if country != 'all' else None,
        job_type=job_type if job_type != 'all' else None,
        contract_type=contract_type if contract_type != 'all' else None,
        seniority=seniority if seniority != 'all' else None,
        search_query=search if search else None,
        sort=sort
    )

    # Pagination logic
    total_jobs = len(all_jobs)
    per_page = 21
    total_pages = max(1, (total_jobs + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_jobs = all_jobs[start_idx:end_idx]

    # Predict salaries for paginated slice (adds predicted_min/max keys to dicts)
    _enrich_salaries(paginated_jobs)

    # Python-level salary sort (now that predicted values are available)
    if sort_intent == 'salary_high':
        paginated_jobs.sort(
            key=lambda j: j.get('predicted_max') or j.get('salary_max') or 0,
            reverse=True
        )
    elif sort_intent == 'salary_low':
        paginated_jobs.sort(
            key=lambda j: j.get('predicted_min') or j.get('salary_min') or 9_999_999
        )

    # Page range to display in pagination controls
    start_page = max(1, page - 2)
    end_page = min(total_pages, page + 2)
    page_range = list(range(start_page, end_page + 1))

    # Optimized filter options via SQL DISTINCT
    filters = get_filter_options()

    return render_template(
        'jobs.html',
        jobs=paginated_jobs,
        total_jobs=total_jobs,
        page=page,
        total_pages=total_pages,
        page_range=page_range,
        countries=filters['countries'],
        seniorities=filters['seniorities'],
        selected_country=country,
        selected_job_type=job_type,
        selected_contract=contract_type,
        selected_seniority=seniority,
        selected_sort=sort,
        search_query=request.args.get('q', ''),
    )


# ── Recommender ───────────────────────────────────────────────────────────────
@main.route('/recommend', methods=['GET', 'POST'])
def recommend_jobs():
    results       = []
    user_skills   = []
    country_f     = None
    job_type_f    = None
    contract_f    = None
    seniority_f   = None
    ats_analysis  = None
    scanned_cv    = False
    cv_filename   = None

    error_message = None

    if request.method == 'POST':
        try:
            cv_file = request.files.get('cv_file')
            if cv_file and cv_file.filename != '':
                cv_filename = cv_file.filename
                ext = os.path.splitext(cv_filename)[1].lower()
                if ext not in ['.pdf', '.docx']:
                    from flask import session
                    lang = session.get('lang', 'en')
                    if lang == 'ar':
                        error_message = "امتداد الملف غير صالح. مسموح فقط بملفات PDF و DOCX."
                    else:
                        error_message = "Invalid file extension. Only PDF and DOCX files are allowed."
                else:
                    file_bytes = cv_file.read()
                    if len(file_bytes) > 5 * 1024 * 1024:
                        from flask import session
                        lang = session.get('lang', 'en')
                        if lang == 'ar':
                            error_message = "حجم الملف كبير جداً. الحد الأقصى المسموح به هو 5 ميجابايت."
                        else:
                            error_message = "File is too large. Maximum size allowed is 5MB."
                    else:
                        from cv_parser import extract_cv_text
                        from rag_assistant import analyze_cv_for_ats
                        
                        cv_text = extract_cv_text(file_bytes, cv_filename)
                        if cv_text:
                            ats_analysis = analyze_cv_for_ats(cv_text)
                            detected_skills = ats_analysis.get('detected_skills', [])
                            user_skills = [s.strip().lower() for s in detected_skills if s.strip()]
                            scanned_cv = True
                            
                            df = recommend(user_skills, top_n=8)
                            results = df.to_dict(orient='records') if not df.empty else []
                        else:
                            from flask import session
                            lang = session.get('lang', 'en')
                            if lang == 'ar':
                                error_message = "فشل في قراءة محتوى السيرة الذاتية."
                            else:
                                error_message = "Failed to extract text from the uploaded CV."
            else:
                skills_raw    = request.form.get('skills', '')
                user_skills   = [s.strip().lower() for s in skills_raw.split(',') if s.strip()]
                country_f     = request.form.get('country') or None
                job_type_f    = request.form.get('job_type') or None
                contract_f    = request.form.get('contract_type') or None
                seniority_f   = request.form.get('seniority') or None
                top_n         = int(request.form.get('top_n', 8))

                if user_skills:
                    df = recommend(
                        user_skills,
                        top_n=top_n,
                        country_filter=country_f,
                        job_type_filter=job_type_f,
                        contract_type_filter=contract_f,
                        seniority_filter=seniority_f,
                    )
                    results = df.to_dict(orient='records') if not df.empty else []

            # Predict salaries for recommended jobs
            if results:
                _enrich_salaries(results)

        except Exception as e:
            import logging
            logging.error(f"[Recommend] Unexpected error: {e}", exc_info=True)
            from flask import session
            lang = session.get('lang', 'en')
            if lang == 'ar':
                error_message = "حدث خطأ أثناء معالجة طلبك. يُرجى المحاولة مرة أخرى."
            else:
                error_message = "Something went wrong while processing your request. Please try again."


    # Optimized filter options via SQL DISTINCT
    filters = get_filter_options()

    return render_template(
        'recommend.html',
        results=results,
        user_skills=user_skills,
        countries=filters['countries'],
        seniorities=filters['seniorities'],
        selected_country=country_f or 'all',
        selected_job_type=job_type_f or 'all',
        selected_contract=contract_f or 'all',
        selected_seniority=seniority_f or 'all',
        ats_analysis=ats_analysis,
        scanned_cv=scanned_cv,
        cv_filename=cv_filename,
        error_message=error_message,
    )


@main.route('/analytics')
def analytics():
    from flask import redirect, url_for
    return redirect(url_for('main.index') + '#analytics')


# ── Admin Dashboard ──────────────────────────────────────────────────────────
@main.route('/admin')
def admin_page():
    from database import get_connection
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Total Jobs
    c.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = c.fetchone()[0]
    
    # 2. Summarized Jobs
    c.execute("SELECT COUNT(*) FROM jobs WHERE summary_en IS NOT NULL AND summary_en != ''")
    summarized_jobs = c.fetchone()[0]
    
    # 3. Last scraper run
    c.execute("SELECT MAX(scraped_at) FROM jobs")
    last_scraped = c.fetchone()[0]
    
    conn.close()
    
    # 4. Token status
    hf_token = os.environ.get('HF_TOKEN', '')
    token_status = "Not Configured"
    masked_token = "---"
    if hf_token:
        token_status = "Active"
        if len(hf_token) > 8:
            masked_token = f"{hf_token[:4]}...{hf_token[-4:]}"
        else:
            masked_token = "***"
            
    # Calculate percentage
    progress = 0
    if total_jobs > 0:
        progress = int((summarized_jobs / total_jobs) * 100)

    return render_template(
        'admin.html',
        total_jobs=total_jobs,
        summarized_jobs=summarized_jobs,
        progress=progress,
        last_scraped=last_scraped,
        token_status=token_status,
        masked_token=masked_token
    )



# ── REST API ─────────────────────────────────────────────────────────────────
@main.route('/api/jobs')
def api_jobs():
    country       = request.args.get('country')
    job_type      = request.args.get('job_type')
    contract_type = request.args.get('contract_type')
    try:
        limit = int(request.args.get('limit', 100))
    except (ValueError, TypeError):
        limit = 100
    jobs = fetch_all_jobs(country=country, job_type=job_type,
                          contract_type=contract_type, limit=limit)
    return jsonify({'count': len(jobs), 'jobs': jobs})


@main.route('/api/recommend', methods=['POST'])
def api_recommend():
    data        = request.get_json(force=True)
    skills      = data.get('skills', [])
    top_n       = int(data.get('top_n', 5))
    country_f   = data.get('country')
    job_type_f  = data.get('job_type')

    if not skills:
        return jsonify({'error': 'skills list required'}), 400

    df = recommend(skills, top_n=top_n, country_filter=country_f,
                   job_type_filter=job_type_f)
    return jsonify({'results': df.to_dict(orient='records') if not df.empty else []})


@main.route('/api/stats')
def api_stats():
    return jsonify(get_stats())


@main.route('/api/refresh', methods=['POST'])
def api_refresh():
    msg = trigger_now()
    
    # Also trigger an immediate database upload attempt in a background thread to give instant feedback
    try:
        from hf_sync import upload_db_to_hf
        import threading
        threading.Thread(target=upload_db_to_hf, daemon=True).start()
    except Exception as e:
        import logging
        logging.warning(f"[Routes] Failed to trigger background HF upload: {e}")
        
    return jsonify({'status': 'ok', 'message': msg})


@main.route('/api/summarize-all', methods=['POST'])
def api_summarize_all():
    """Trigger continuous AI summarization backfill for all jobs in a background thread."""
    import threading
    from etl import run_etl
    threading.Thread(target=run_etl, daemon=True).start()
    return jsonify({'status': 'ok', 'message': 'Continuous AI summarization backfill started in the background.'})


@main.route('/api/reset-summaries', methods=['POST'])
def api_reset_summaries():
    """Clear all summaries to allow them to be regenerated with a new prompt style."""
    from database import get_connection
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE jobs SET summary_en = NULL, summary_ar = NULL")
    conn.commit()
    conn.close()
    # Immediately upload cleared DB to HF so reset persists on next restart
    try:
        import threading
        from hf_sync import upload_db_to_hf
        threading.Thread(target=upload_db_to_hf, daemon=True).start()
    except Exception as e:
        import logging
        logging.warning(f"[Routes] HF upload after reset failed: {e}")
    return jsonify({'status': 'ok', 'message': 'All summaries cleared and synced to cloud. You can now trigger the summarizer again.'})



@main.route('/api/salary-predict', methods=['POST'])
def api_salary_predict():
    """Predict salary range for a given job description."""
    data = request.get_json(force=True)
    title         = data.get('title', '')
    description   = data.get('description', '')
    country       = data.get('country', '')
    job_type      = data.get('job_type', 'onsite')
    contract_type = data.get('contract_type', 'full-time')

    if not title:
        return jsonify({'error': 'title is required'}), 400

    result = predict_salary(title, description, country, job_type, contract_type)
    return jsonify(result)


@main.route('/api/health')
def api_health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


# ── Chatbot UI ───────────────────────────────────────────────────────────────
@main.route('/chat')
def chat():
    from flask import redirect, url_for
    return redirect(url_for('main.index'))


@main.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(force=True)
    message = data.get('message', '')
    history = data.get('history', [])
    
    if not message:
        return jsonify({'error': 'message is required'}), 400
        
    response = chat_with_coach(message, chat_history=history)
    return jsonify({'response': response})


# ── Language Switcher ────────────────────────────────────────────────────────
@main.route('/change-lang/<lang>')
def change_lang(lang):
    from flask import redirect, request, url_for, session, make_response
    response = make_response(redirect(request.referrer or url_for('main.index')))
    if lang in ['en', 'ar']:
        session['lang'] = lang
        # Set a plain cookie for 30 days to persist language across session restarts or secret key regeneration
        response.set_cookie('lang', lang, max_age=30*24*60*60, path='/')
    return response
