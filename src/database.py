import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.db')

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT UNIQUE NOT NULL
        )
    ''')

    # country + job_type stored now — will power the country filter toggle later
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id     TEXT UNIQUE,
            title         TEXT NOT NULL,
            company_id    INTEGER REFERENCES companies(id),
            location      TEXT,
            country       TEXT,
            job_type      TEXT DEFAULT 'onsite',   -- onsite | remote | hybrid
            salary_min    REAL,
            salary_max    REAL,
            description   TEXT,
            source        TEXT DEFAULT 'adzuna',
            source_url    TEXT,
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

    conn.commit()
    conn.close()
    print("[DB] Tables ready.")

def insert_job(job: dict) -> int | None:
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        'INSERT OR IGNORE INTO companies (name) VALUES (?)',
        (job.get('company', 'Unknown'),)
    )
    c.execute('SELECT id FROM companies WHERE name = ?', (job.get('company', 'Unknown'),))
    company_id = c.fetchone()[0]

    try:
        c.execute('''
            INSERT OR IGNORE INTO jobs
                (source_id, title, company_id, location, country, job_type,
                 salary_min, salary_max, description, source, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.get('source_id'),
            job.get('title'),
            company_id,
            job.get('location'),
            job.get('country'),
            job.get('job_type', 'onsite'),
            job.get('salary_min'),
            job.get('salary_max'),
            job.get('description'),
            job.get('source', 'adzuna'),
            job.get('source_url'),
        ))
        conn.commit()
        job_id = c.lastrowid
    except Exception as e:
        print(f"[DB] insert_job error: {e}")
        job_id = None
    finally:
        conn.close()

    return job_id

def insert_skill(name: str, category: str = None) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO skills (name, category) VALUES (?, ?)', (name, category))
    conn.commit()
    c.execute('SELECT id FROM skills WHERE name = ?', (name,))
    skill_id = c.fetchone()[0]
    conn.close()
    return skill_id

def insert_job_skill(job_id: int, skill_id: int, score: float):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO job_skills (job_id, skill_id, tfidf_score)
        VALUES (?, ?, ?)
    ''', (job_id, skill_id, score))
    conn.commit()
    conn.close()

def fetch_all_jobs() -> list[dict]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT j.*, co.name AS company_name
        FROM jobs j
        LEFT JOIN companies co ON j.company_id = co.id
    ''')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
