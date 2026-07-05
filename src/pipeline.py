"""
pipeline.py — pulls jobs from Adzuna API and stores them in SQLite.

Usage:
    python src/pipeline.py --keywords "data scientist" --country gb --pages 5
"""

import logging
import os
import argparse
import requests
from dotenv import load_dotenv
from database import init_db, insert_job

load_dotenv()

APP_ID  = os.getenv('ADZUNA_APP_ID')
APP_KEY = os.getenv('ADZUNA_APP_KEY')

BASE_URL = 'https://api.adzuna.com/v1/api/jobs/{country}/search/{page}'

# Countries supported by Adzuna (useful later for the country filter feature)
SUPPORTED_COUNTRIES = {
    'gb': 'United Kingdom',
    'us': 'United States',
    'au': 'Australia',
    'ca': 'Canada',
    'de': 'Germany',
    'fr': 'France',
    'in': 'India',
    'sg': 'Singapore',
    'ae': 'UAE',
    'za': 'South Africa',
}

def detect_job_type(title: str, description: str) -> str:
    """Detect remote / hybrid / onsite from title and description text."""
    text = (title + ' ' + description).lower()
    if 'remote' in text:
        return 'remote'
    if 'hybrid' in text:
        return 'hybrid'
    return 'onsite'

def fetch_jobs(keywords: str, country: str = 'gb', pages: int = 5) -> list[dict]:
    if not APP_ID or not APP_KEY:
        raise ValueError("Missing ADZUNA_APP_ID or ADZUNA_APP_KEY in .env")

    jobs = []
    for page in range(1, pages + 1):
        url = BASE_URL.format(country=country, page=page)
        params = {
            'app_id':         APP_ID,
            'app_key':        APP_KEY,
            'what':           keywords,
            'results_per_page': 50,
            'content-type':   'application/json',
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = data.get('results', [])
            logging.info(f"[pipeline] page {page}: got {len(results)} jobs")
            jobs.extend(results)
        except requests.RequestException as e:
            logging.info(f"[pipeline] error on page {page}: {e}")
            break

    return jobs

def normalize(raw: dict, country: str) -> dict:
    salary = raw.get('salary_min'), raw.get('salary_max')
    desc   = raw.get('description', '')
    title  = raw.get('title', '')

    return {
        'source_id':   raw.get('id'),
        'title':       title,
        'company':     raw.get('company', {}).get('display_name', 'Unknown'),
        'location':    raw.get('location', {}).get('display_name', ''),
        'country':     SUPPORTED_COUNTRIES.get(country, country.upper()),
        'job_type':    detect_job_type(title, desc),
        'salary_min':  salary[0],
        'salary_max':  salary[1],
        'description': desc,
        'source':      'adzuna',
        'source_url':  raw.get('redirect_url', ''),
        'posted_at':   raw.get('created'),
    }

def run(keywords: str, country: str = 'gb', pages: int = 5):
    init_db()
    raw_jobs = fetch_jobs(keywords, country, pages)
    saved = 0
    for raw in raw_jobs:
        job = normalize(raw, country)
        job_id = insert_job(job)
        if job_id:
            saved += 1
    logging.info(f"[pipeline] done — saved {saved}/{len(raw_jobs)} jobs to DB.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', default='data scientist', help='Job search keywords')
    parser.add_argument('--country',  default='gb',             help='Country code (gb, us, ...)')
    parser.add_argument('--pages',    default=5, type=int,      help='Pages to fetch (50 jobs each)')
    args = parser.parse_args()
    run(args.keywords, args.country, args.pages)