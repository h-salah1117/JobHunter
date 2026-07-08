"""
database.py — SQLite schema + CRUD helpers.
v2: added contract_type, raw_post_text, source expanded to adzuna|social|manual
"""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.db')


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id     TEXT UNIQUE,
            title         TEXT NOT NULL,
            company_id    INTEGER REFERENCES companies(id),
            location      TEXT,
            country       TEXT,
            job_type      TEXT DEFAULT 'onsite',
            contract_type TEXT DEFAULT 'full-time',
            salary_min    REAL,
            salary_max    REAL,
            description   TEXT,
            source        TEXT DEFAULT 'adzuna',
            source_url    TEXT,
            raw_post_text TEXT,
            scraped_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS skills (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT UNIQUE NOT NULL,
            category TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS job_skills (
            job_id      INTEGER REFERENCES jobs(id),
            skill_id    INTEGER REFERENCES skills(id),
            tfidf_score REAL,
            PRIMARY KEY (job_id, skill_id)
        )
    ''')

    # migration: add new columns if they don't exist yet (safe to run repeatedly)
    _safe_add_column(c, 'jobs', 'contract_type', "TEXT DEFAULT 'full-time'")
    _safe_add_column(c, 'jobs', 'raw_post_text', 'TEXT')
    _safe_add_column(c, 'jobs', 'seniority', 'TEXT')
    _safe_add_column(c, 'jobs', 'summary_en', 'TEXT')
    _safe_add_column(c, 'jobs', 'summary_ar', 'TEXT')
    _safe_add_column(c, 'jobs', 'posted_at', 'TEXT')

    conn.commit()
    conn.close()
    import logging
    logging.info('[DB] Schema ready.')


def _safe_add_column(cursor, table, column, definition):
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    except sqlite3.OperationalError:
        pass  # column already exists


def insert_job(job: dict) -> int | None:
    conn = get_connection()
    c = conn.cursor()

    c.execute('INSERT OR IGNORE INTO companies (name) VALUES (?)',
              (job.get('company', 'Unknown'),))
    c.execute('SELECT id FROM companies WHERE name = ?',
              (job.get('company', 'Unknown'),))
    company_id = c.fetchone()[0]

    try:
        c.execute('''
            INSERT OR IGNORE INTO jobs
                (source_id, title, company_id, location, country,
                 job_type, contract_type, salary_min, salary_max,
                 description, source, source_url, raw_post_text, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.get('source_id'),
            job.get('title'),
            company_id,
            job.get('location'),
            job.get('country'),
            job.get('job_type', 'onsite'),
            job.get('contract_type', 'full-time'),
            job.get('salary_min'),
            job.get('salary_max'),
            job.get('description'),
            job.get('source', 'adzuna'),
            job.get('source_url'),
            job.get('raw_post_text'),
            job.get('posted_at'),
        ))
        conn.commit()
        job_id = c.lastrowid
    except Exception as e:
        import logging
        logging.error(f'[DB] insert_job error: {e}')
        job_id = None
    finally:
        conn.close()

    return job_id



def update_job_summaries(job_id: int, summary_en: str, summary_ar: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE jobs
        SET summary_en = ?, summary_ar = ?
        WHERE id = ?
    ''', (summary_en, summary_ar, job_id))
    conn.commit()
    conn.close()


def insert_skill(name: str, category: str = None, conn = None) -> int:
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO skills (name, category) VALUES (?, ?)',
              (name, category))
    if should_close:
        conn.commit()
    c.execute('SELECT id FROM skills WHERE name = ?', (name,))
    skill_id = c.fetchone()[0]
    if should_close:
        conn.close()
    return skill_id


def insert_job_skill(job_id: int, skill_id: int, score: float, conn = None):
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO job_skills (job_id, skill_id, tfidf_score)
        VALUES (?, ?, ?)
    ''', (job_id, skill_id, score))
    if should_close:
        conn.commit()
        conn.close()


def fetch_all_jobs(
    country: str = None,
    job_type: str = None,
    contract_type: str = None,
    seniority: str = None,
    search_query: str = None,
    sort: str = 'newest',
    limit: int = 500,
) -> list[dict]:
    conn = get_connection()
    c = conn.cursor()

    query = '''
        SELECT j.*, co.name AS company_name
        FROM jobs j
        LEFT JOIN companies co ON j.company_id = co.id
        WHERE datetime(coalesce(j.posted_at, j.scraped_at)) >= datetime('now', '-30 days')
    '''
    params = []

    if country and country != 'all':
        query += ' AND LOWER(j.country) = LOWER(?)'
        params.append(country)
    if job_type and job_type != 'all':
        query += ' AND j.job_type = ?'
        params.append(job_type)
    if contract_type and contract_type != 'all':
        query += ' AND j.contract_type = ?'
        params.append(contract_type)
    if seniority and seniority != 'all':
        query += ' AND j.seniority = ?'
        params.append(seniority)
    if search_query:
        query += ' AND (j.title LIKE ? OR co.name LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    # Always fetch newest first from DB; salary sort is done in Python after enrichment
    query += ' ORDER BY coalesce(j.posted_at, j.scraped_at) DESC'
        
    query += ' LIMIT ?'
    params.append(limit)

    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows, sort  # return sort intent so caller can sort after enrichment



def get_stats() -> dict:
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM jobs WHERE datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'remote' AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    remote = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM jobs WHERE contract_type = 'internship' AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    internships = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT company_id) FROM jobs WHERE datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    companies = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT country) FROM jobs WHERE datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    countries = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM jobs WHERE source = 'social' AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')")
    social = c.fetchone()[0]

    c.execute('SELECT MAX(scraped_at) FROM jobs')
    last_updated = c.fetchone()[0]

    conn.close()
    return {
        'total': total,
        'remote': remote,
        'internships': internships,
        'companies': companies,
        'countries': countries,
        'social_posts': social,
        'last_updated': last_updated,
    }


def get_filter_options() -> dict:
    """Optimized SQL DISTINCT queries for filter dropdowns."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        SELECT DISTINCT country 
        FROM jobs 
        WHERE country IS NOT NULL 
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        ORDER BY country
    ''')
    countries = [r[0] for r in c.fetchall()]

    c.execute('''
        SELECT DISTINCT seniority 
        FROM jobs 
        WHERE seniority IS NOT NULL 
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        ORDER BY seniority
    ''')
    seniorities = [r[0] for r in c.fetchall()]

    conn.close()
    return {'countries': countries, 'seniorities': seniorities}


def get_seniority_breakdown() -> list[dict]:
    """Seniority distribution for donut chart."""
    conn = get_connection()
    df = pd.read_sql('''
        SELECT seniority, COUNT(*) as count
        FROM jobs
        WHERE seniority IS NOT NULL
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        GROUP BY seniority
        ORDER BY count DESC
    ''', conn)
    conn.close()
    return df.to_dict(orient='records')


def get_avg_salary_by_seniority() -> list[dict]:
    """Average salary range grouped by seniority level, normalized to GBP (£)."""
    conn = get_connection()
    df = pd.read_sql('''
        SELECT seniority, country, salary_min, salary_max
        FROM jobs
        WHERE salary_min IS NOT NULL AND seniority IS NOT NULL
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
    ''', conn)
    conn.close()

    if df.empty:
        return []

    # Convert UK salaries from GBP to USD (1 GBP ~ 1.25 USD)
    gbp_mask = df['country'].str.lower().isin(['united kingdom', 'gb', 'uk'])
    df.loc[gbp_mask, 'salary_min'] = df.loc[gbp_mask, 'salary_min'] * 1.25
    df.loc[gbp_mask, 'salary_max'] = df.loc[gbp_mask, 'salary_max'] * 1.25


    grouped = df.groupby('seniority').agg(
        avg_min=('salary_min', 'mean'),
        avg_max=('salary_max', 'mean'),
        job_count=('salary_min', 'count')
    ).reset_index()

    grouped['avg_min'] = grouped['avg_min'].round(0)
    grouped['avg_max'] = grouped['avg_max'].round(0)
    grouped = grouped.sort_values(by='avg_max', ascending=False)

    return grouped.to_dict(orient='records')
