"""
jobspy_scraper.py — uses python-jobspy to scrape Bayt, Indeed, Google Jobs.

Bayt is the largest Arab job board (Egypt, Saudi, UAE, Kuwait, etc.)
Safe to run on HuggingFace Spaces — no login, no Selenium needed.

Install: pip install python-jobspy

Usage:
    python src/jobspy_scraper.py
"""

import sys, os, uuid, time
sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, insert_job

# ── Arab/Egypt focused keywords ──────────────────────────────────────────────
ARAB_KEYWORDS = [
    'data scientist',
    'data analyst',
    'machine learning engineer',
    'nlp engineer',
    'ai engineer',
    'business intelligence',
    'data engineer',
    'python developer',
    'software engineer',
]

# ── Location targets (Arab market) ───────────────────────────────────────────
LOCATIONS = [
    'Egypt',
    'Cairo',
    'Saudi Arabia',
    'UAE',
    'Kuwait',
    'Jordan',
]

# ── country_indeed codes ──────────────────────────────────────────────────────
INDEED_COUNTRIES = {
    'Egypt':        'Egypt',
    'Saudi Arabia': 'Saudi Arabia',
    'UAE':          'United Arab Emirates',
    'Kuwait':       'Kuwait',
    'Jordan':       'Jordan',
}

def _detect_seniority(title: str, desc: str) -> str:
    text = (title + ' ' + desc).lower()
    if any(w in text for w in ['senior', 'lead', 'principal', 'staff', 'head of']):
        return 'senior'
    if any(w in text for w in ['junior', 'entry', 'graduate', 'fresh', 'intern']):
        return 'junior'
    return 'mid'

def _normalize_jobspy_row(row, source_site: str) -> dict:
    """Convert a JobSpy DataFrame row to our DB schema."""
    title    = str(row.get('title', '') or '')
    desc     = str(row.get('description', '') or '')
    company  = str(row.get('company', '') or 'Unknown')
    location = str(row.get('location', '') or '')
    country  = str(row.get('country', '') or '')
    url      = str(row.get('job_url', '') or '')

    # salary
    sal_min = row.get('min_amount')
    sal_max = row.get('max_amount')
    try:
        sal_min = float(sal_min) if sal_min and str(sal_min) != 'nan' else None
        sal_max = float(sal_max) if sal_max and str(sal_max) != 'nan' else None
    except (ValueError, TypeError):
        sal_min, sal_max = None, None

    # job type
    jt = str(row.get('job_type', '') or '').lower()
    if 'remote' in jt or 'remote' in title.lower():
        job_type = 'remote'
    elif 'hybrid' in jt:
        job_type = 'hybrid'
    else:
        job_type = 'onsite'

    # contract type
    if 'internship' in jt or 'intern' in title.lower():
        contract_type = 'internship'
    elif 'part' in jt:
        contract_type = 'part-time'
    elif 'contract' in jt:
        contract_type = 'contract'
    else:
        contract_type = 'full-time'

    return {
        'source_id':     f"{source_site}_{uuid.uuid5(uuid.NAMESPACE_URL, url or uuid.uuid4().hex).hex[:12]}",
        'title':         title,
        'company':       company,
        'location':      location,
        'country':       country or location.split(',')[-1].strip(),
        'job_type':      job_type,
        'contract_type': contract_type,
        'salary_min':    sal_min,
        'salary_max':    sal_max,
        'description':   desc[:3000],
        'source':        source_site,
        'source_url':    url,
        'raw_post_text': None,
    }

def scrape_bayt(keywords: list[str] = None, results_per_kw: int = 50) -> int:
    """Scrape Bayt.com — largest Arab job board."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print('[JobSpy] Install: pip install python-jobspy')
        return 0

    kws   = keywords or ARAB_KEYWORDS
    saved = 0

    for kw in kws:
        for location in LOCATIONS[:3]:   # Egypt, Cairo, Saudi Arabia
            print(f'[Bayt] scraping "{kw}" in {location}...')
            try:
                df = scrape_jobs(
                    site_name=['bayt'],
                    search_term=kw,
                    location=location,
                    results_wanted=results_per_kw,
                    hours_old=168,   # last week
                )
                if df is None or df.empty:
                    continue

                df['country'] = location
                for _, row in df.iterrows():
                    job = _normalize_jobspy_row(row.to_dict(), 'bayt')
                    if insert_job(job):
                        saved += 1

                print(f'[Bayt] "{kw}" / {location}: {len(df)} found')
                time.sleep(2)

            except Exception as e:
                print(f'[Bayt] error for "{kw}" / {location}: {e}')
                time.sleep(3)

    return saved

def scrape_indeed_arab(keywords: list[str] = None, results_per_kw: int = 50) -> int:
    """Scrape Indeed for Arab market."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print('[JobSpy] Install: pip install python-jobspy')
        return 0

    kws   = keywords or ARAB_KEYWORDS[:5]
    saved = 0

    for kw in kws:
        for location, country_code in INDEED_COUNTRIES.items():
            print(f'[Indeed] scraping "{kw}" in {location}...')
            try:
                df = scrape_jobs(
                    site_name=['indeed'],
                    search_term=kw,
                    location=location,
                    results_wanted=results_per_kw,
                    country_indeed=country_code,
                    hours_old=168,
                )
                if df is None or df.empty:
                    continue

                df['country'] = location
                for _, row in df.iterrows():
                    job = _normalize_jobspy_row(row.to_dict(), 'indeed')
                    if insert_job(job):
                        saved += 1

                print(f'[Indeed] "{kw}" / {location}: {len(df)} found')
                time.sleep(2)

            except Exception as e:
                print(f'[Indeed] error: {e}')
                time.sleep(3)

    return saved

def scrape_google_jobs(keywords: list[str] = None, results_per_kw: int = 50) -> int:
    """Scrape Google Jobs for Arab/Egypt market."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return 0

    kws   = keywords or ARAB_KEYWORDS[:4]
    saved = 0

    for kw in kws:
        for location in ['Egypt', 'Cairo Egypt', 'Saudi Arabia']:
            print(f'[Google Jobs] scraping "{kw}" in {location}...')
            try:
                df = scrape_jobs(
                    site_name=['google'],
                    search_term=kw,
                    google_search_term=f'{kw} jobs in {location}',
                    location=location,
                    results_wanted=results_per_kw,
                    hours_old=168,
                )
                if df is None or df.empty:
                    continue

                df['country'] = location.split()[-1]
                for _, row in df.iterrows():
                    job = _normalize_jobspy_row(row.to_dict(), 'google_jobs')
                    if insert_job(job):
                        saved += 1

                print(f'[Google Jobs] "{kw}" / {location}: {len(df)} found')
                time.sleep(2)

            except Exception as e:
                print(f'[Google Jobs] error: {e}')
                time.sleep(3)

    return saved

def run(keywords: list[str] = None) -> int:
    init_db()
    total = 0
    total += scrape_bayt(keywords)
    total += scrape_indeed_arab(keywords)
    total += scrape_google_jobs(keywords)
    print(f'[JobSpy] total saved: {total}')
    return total

if __name__ == '__main__':
    run()
