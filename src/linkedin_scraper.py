"""
linkedin_scraper.py — scrapes LinkedIn JOBS PAGE (not profiles/feed).

Scraping the public jobs search page is significantly safer than scraping
profiles or feeds — it's public data with no login required for basic results.

⚠️  Use with caution on HuggingFace — LinkedIn blocks datacenter IPs.
     Recommended: run locally to seed DB, then deploy the pre-filled DB.
     Set SCRAPER_MODE=local in .env to fully enable.

Usage:
    python src/linkedin_scraper.py --keywords "data scientist" --location "Egypt" --pages 3
"""

import re
import time
import uuid
import argparse
import requests
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, insert_job

SCRAPER_MODE = os.getenv('SCRAPER_MODE', 'production').lower()

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

BASE_URL = 'https://www.linkedin.com/jobs/search/'

def _detect_job_type(text: str) -> str:
    t = text.lower()
    if 'remote' in t: return 'remote'
    if 'hybrid' in t: return 'hybrid'
    return 'onsite'

def _detect_contract(text: str) -> str:
    t = text.lower()
    if 'intern' in t:   return 'internship'
    if 'part-time' in t or 'part time' in t: return 'part-time'
    if 'contract' in t: return 'contract'
    return 'full-time'

def scrape_linkedin_jobs(
    keywords: str = 'data scientist',
    location: str = 'Egypt',
    pages: int = 3,
) -> list[dict]:
    """
    Scrapes LinkedIn public job listings (no login required).
    Returns list of job dicts.
    """
    if SCRAPER_MODE == 'production':
        print('[LinkedIn] Production mode detected — skipping to avoid IP ban on HuggingFace.')
        print('[LinkedIn] Run locally with SCRAPER_MODE=local to collect data.')
        return []

    jobs = []

    for page in range(pages):
        params = {
            'keywords': keywords,
            'location': location,
            'start':    page * 25,
            'f_TPR':    'r604800',   # last week
        }

        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f'[LinkedIn] request error page {page}: {e}')
            break

        soup = BeautifulSoup(resp.text, 'html.parser')
        cards = soup.select('div.job-search-card') or \
                soup.select('li.jobs-search-results__list-item') or \
                soup.select('[data-job-id]')

        if not cards:
            print(f'[LinkedIn] No cards found on page {page} — possible block or selector change.')
            break

        for card in cards:
            try:
                title_el   = card.select_one('h3, .base-search-card__title')
                company_el = card.select_one('h4, .base-search-card__subtitle')
                loc_el     = card.select_one('.job-search-card__location, [class*="location"]')
                link_el    = card.select_one('a[href*="/jobs/view/"]')

                if not title_el or not link_el:
                    continue

                title    = title_el.get_text(strip=True)
                company  = company_el.get_text(strip=True) if company_el else 'Unknown'
                location_str = loc_el.get_text(strip=True) if loc_el else location
                url      = link_el['href'].split('?')[0]   # clean URL

                meta_text = card.get_text(separator=' ')

                jobs.append({
                    'source_id':     f"li_{uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]}",
                    'title':         title,
                    'company':       company,
                    'location':      location_str,
                    'country':       'Egypt' if 'egypt' in location.lower() else location,
                    'job_type':      _detect_job_type(meta_text),
                    'contract_type': _detect_contract(meta_text),
                    'salary_min':    None,
                    'salary_max':    None,
                    'description':   meta_text[:1500],
                    'source':        'linkedin',
                    'source_url':    url,
                    'raw_post_text': None,
                })

            except Exception:
                continue

        print(f'[LinkedIn] page {page+1}: {len(cards)} cards found')
        time.sleep(3)   # polite delay

    return jobs


def run(keywords: str = 'data scientist', location: str = 'Egypt', pages: int = 3):
    init_db()
    jobs  = scrape_linkedin_jobs(keywords, location, pages)
    saved = sum(1 for j in jobs if insert_job(j))
    print(f'[LinkedIn] saved {saved}/{len(jobs)} jobs.')
    return saved


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', default='data scientist')
    parser.add_argument('--location', default='Egypt')
    parser.add_argument('--pages',    default=3, type=int)
    args = parser.parse_args()
    run(args.keywords, args.location, args.pages)
