"""
wuzzuf_scraper.py — scrapes jobs from Wuzzuf.net (Egypt's largest job board).

Safe to run locally and on HuggingFace Spaces.
Uses requests + BeautifulSoup (no Selenium needed).

Usage:
    python src/wuzzuf_scraper.py --keywords "data scientist" --pages 5
"""

import logging
import re
import time
import uuid
import argparse
import requests
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, insert_job

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

BASE_URL = 'https://wuzzuf.net/search/jobs/'

# ── Helpers ──────────────────────────────────────────────────────────────────

def _detect_job_type(text: str) -> str:
    t = text.lower()
    if 'remote' in t or 'work from home' in t or 'wfh' in t:
        return 'remote'
    if 'hybrid' in t:
        return 'hybrid'
    return 'onsite'

def _detect_contract(text: str) -> str:
    t = text.lower()
    if 'intern' in t or 'internship' in t:
        return 'internship'
    if 'part time' in t or 'part-time' in t:
        return 'part-time'
    if 'freelance' in t or 'contract' in t:
        return 'contract'
    return 'full-time'

def _parse_salary(text: str):
    """Try to extract min/max salary from string like '5,000 - 10,000 EGP'."""
    nums = re.findall(r'[\d,]+', text.replace(',', ''))
    nums = [int(n) for n in nums if n.isdigit() and int(n) > 100]
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        return float(nums[0]), None
    return None, None

# ── Search page scraper ───────────────────────────────────────────────────────

def scrape_search_page(keywords: str, page: int = 1) -> list[dict]:
    """Scrape one search results page — returns list of partial job dicts."""
    params = {
        'q':    keywords,
        'a':    'navigo',
        'start': (page - 1) * 15,
    }
    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.info(f'[Wuzzuf] request error page {page}: {e}')
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    job_cards = soup.select('div[class*="css-"][data-jobid]') or \
                soup.select('article[data-jobid]') or \
                soup.select('.job-card-component')

    # Fallback: any card with a link to /jobs/p/
    if not job_cards:
        job_cards = [
            a.find_parent('div') or a.find_parent('article')
            for a in soup.select('a[href*="/jobs/p/"]')
            if a.find_parent('div') or a.find_parent('article')
        ]
        job_cards = list({id(c): c for c in job_cards if c}.values())

    jobs = []
    for card in job_cards:
        try:
            # Title + URL
            link_el = card.select_one('a[href*="/jobs/p/"]')
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            url   = 'https://wuzzuf.net' + link_el['href'] if link_el['href'].startswith('/') else link_el['href']

            # Company
            company_el = card.select_one('a[href*="/company/"]') or \
                         card.select_one('[class*="company"]')
            company = company_el.get_text(strip=True) if company_el else 'Unknown'

            # Location
            location_el = card.select_one('[class*="location"]') or \
                          card.select_one('[class*="city"]')
            location = location_el.get_text(strip=True) if location_el else 'Egypt'

            # Tags (job type, contract, experience)
            tags_text = ' '.join(
                t.get_text(strip=True)
                for t in card.select('[class*="tag"], [class*="type"], [class*="label"]')
            )

            jobs.append({
                'title':    title,
                'company':  company,
                'location': location,
                'tags':     tags_text,
                'url':      url,
            })
        except Exception:
            continue

    logging.info(f'[Wuzzuf] page {page}: found {len(jobs)} jobs')
    return jobs

# ── Detail page scraper ───────────────────────────────────────────────────────

def scrape_job_detail(job_url: str) -> dict:
    """Fetch full job description from the job detail page."""
    try:
        resp = requests.get(job_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Description
    desc_el = soup.select_one('[class*="description"]') or \
              soup.select_one('[class*="details"]') or \
              soup.select_one('section')
    description = desc_el.get_text(separator=' ', strip=True) if desc_el else ''

    # Salary
    salary_el = soup.find(string=re.compile(r'EGP|salary|راتب', re.I))
    sal_min, sal_max = (None, None)
    if salary_el:
        sal_min, sal_max = _parse_salary(salary_el)

    return {
        'description': description[:3000],
        'salary_min':  sal_min,
        'salary_max':  sal_max,
    }

# ── Main runner ───────────────────────────────────────────────────────────────

def run(keywords: str = 'data', pages: int = 5, fetch_details: bool = True):
    init_db()
    total_saved = 0

    for page in range(1, pages + 1):
        partial_jobs = scrape_search_page(keywords, page)
        if not partial_jobs:
            break

        for pj in partial_jobs:
            detail = {}
            if fetch_details:
                detail = scrape_job_detail(pj['url'])
                time.sleep(1.2)   # polite delay — avoid rate limiting

            combined_text = pj['tags'] + ' ' + detail.get('description', '')

            job = {
                'source_id':     f"wuzzuf_{uuid.uuid5(uuid.NAMESPACE_URL, pj['url']).hex[:12]}",
                'title':         pj['title'],
                'company':       pj['company'],
                'location':      pj['location'],
                'country':       'Egypt',
                'job_type':      _detect_job_type(combined_text),
                'contract_type': _detect_contract(combined_text),
                'salary_min':    detail.get('salary_min'),
                'salary_max':    detail.get('salary_max'),
                'description':   detail.get('description', pj['tags']),
                'source':        'wuzzuf',
                'source_url':    pj['url'],
                'raw_post_text': None,
            }

            if insert_job(job):
                total_saved += 1

        time.sleep(2)   # delay between pages

    logging.info(f'[Wuzzuf] done — saved {total_saved} jobs.')
    return total_saved


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', default='data scientist', help='Search keywords')
    parser.add_argument('--pages',    default=5, type=int,     help='Pages to scrape')
    parser.add_argument('--no-details', action='store_true',   help='Skip detail pages (faster)')
    args = parser.parse_args()
    run(args.keywords, args.pages, fetch_details=not args.no_details)
