"""
app/routes.py — all Flask URL routes.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
from flask import Blueprint, render_template, request, jsonify

from database import (
    fetch_all_jobs, get_stats, get_filter_options,
    get_seniority_breakdown, get_avg_salary_by_seniority,
)
from recommender import recommend, get_top_skills, get_salary_stats
from nlp_analysis import (
    generate_wordcloud, cluster_jobs, skill_trends,
    skill_cooccurrence, contract_type_breakdown, country_salary_heatmap,
)
from scheduler import get_last_run, trigger_now
from salary_model import predict_salary

main = Blueprint('main', __name__)


# ── Dashboard ────────────────────────────────────────────────────────────────
@main.route('/')
def index():
    stats       = get_stats()
    top_skills  = get_top_skills(15)
    if hasattr(top_skills, 'to_dict'):
        top_skills = top_skills.to_dict(orient='records')
    last_run    = get_last_run()

    # contract type breakdown for pie chart
    contract_breakdown = contract_type_breakdown()

    return render_template(
        'index.html',
        stats=stats,
        top_skills=top_skills,
        contract_breakdown=contract_breakdown,
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

    all_jobs = fetch_all_jobs(
        country=country if country != 'all' else None,
        job_type=job_type if job_type != 'all' else None,
        contract_type=contract_type if contract_type != 'all' else None,
        seniority=seniority if seniority != 'all' else None,
    )

    if search:
        all_jobs = [
            j for j in all_jobs
            if search in j.get('title', '').lower()
            or search in j.get('company_name', '').lower()
        ]

    # Predict salaries for jobs without them
    for j in all_jobs:
        s_min = j.get('salary_min')
        s_max = j.get('salary_max')
        if s_min != s_min:
            s_min = None
            j['salary_min'] = None
        if s_max != s_max:
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

    # Optimized filter options via SQL DISTINCT
    filters = get_filter_options()

    return render_template(
        'jobs.html',
        jobs=all_jobs,
        countries=filters['countries'],
        seniorities=filters['seniorities'],
        selected_country=country,
        selected_job_type=job_type,
        selected_contract=contract_type,
        selected_seniority=seniority,
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

    if request.method == 'POST':
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

            # Predict salaries for recommended jobs without them
            for j in results:
                s_min = j.get('salary_min')
                s_max = j.get('salary_max')
                if s_min != s_min:
                    s_min = None
                    j['salary_min'] = None
                if s_max != s_max:
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
    )


# ── Analytics ────────────────────────────────────────────────────────────────
@main.route('/analytics')
def analytics():
    wordcloud_b64 = generate_wordcloud()
    clusters      = cluster_jobs(n_clusters=5)
    trends        = skill_trends()
    cooc          = skill_cooccurrence(top_n=12)
    salary_data   = country_salary_heatmap()

    # Week 3: seniority + salary charts
    seniority_breakdown  = get_seniority_breakdown()
    salary_by_seniority  = get_avg_salary_by_seniority()

    return render_template(
        'analytics.html',
        wordcloud_b64=wordcloud_b64,
        clusters_json=json.dumps(clusters),
        trends_json=json.dumps(trends),
        cooc_json=json.dumps(cooc),
        salary_json=json.dumps(salary_data),
        seniority_json=json.dumps(seniority_breakdown),
        salary_seniority_json=json.dumps(salary_by_seniority),
    )


# ── REST API ─────────────────────────────────────────────────────────────────
@main.route('/api/jobs')
def api_jobs():
    country       = request.args.get('country')
    job_type      = request.args.get('job_type')
    contract_type = request.args.get('contract_type')
    limit         = int(request.args.get('limit', 100))
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
    return jsonify({'status': 'ok', 'message': msg})


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
