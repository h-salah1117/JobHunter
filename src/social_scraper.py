"""
social_scraper.py — unified scraper entry point.

Sources:
  Always (production + local):
    - Wuzzuf        (Egypt's #1 job board — BeautifulSoup)
    - Bayt          (Arab world's #1 job board — JobSpy)
    - Indeed Arab   (Egypt, Saudi, UAE, Kuwait, Jordan — JobSpy)
    - Google Jobs   (Arab locations — JobSpy)

  Local only (SCRAPER_MODE=local):
    - Facebook Groups (Selenium — Egyptian job groups)
"""

import logging
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

SCRAPER_MODE = os.getenv('SCRAPER_MODE', 'production').lower()

ARAB_KEYWORDS = [
    'data scientist',
    'data analyst',
    'machine learning',
    'nlp engineer',
    'ai engineer',
    'business intelligence',
    'data engineer',
    'python developer',
    'intern data',
]

def run(keywords: list[str] = None):
    kws   = keywords or ARAB_KEYWORDS
    total = 0

    # ── Always safe (production + local) ────────────────────
    logging.info('[Scraper] Running Wuzzuf...')
    from wuzzuf_scraper import run as wuzzuf_run
    for kw in kws[:5]:
        total += wuzzuf_run(keywords=kw, pages=3)

    logging.info('[Scraper] Running JobSpy (Bayt + Indeed + Google Jobs)...')
    from jobspy_scraper import run as jobspy_run
    total += jobspy_run(kws[:5])

    # ── Local only ───────────────────────────────────────────
    if SCRAPER_MODE == 'local':
        logging.info('[Scraper] Running Facebook Groups (local only)...')
        from facebook_scraper import run as fb_run
        total += fb_run()

    logging.info(f'[Scraper] Total jobs saved this run: {total}')
    return total

if __name__ == '__main__':
    import sys
    kws = sys.argv[1:] if len(sys.argv) > 1 else None
    run(kws)

