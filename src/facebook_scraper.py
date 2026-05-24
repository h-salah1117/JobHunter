"""
facebook_scraper.py — Scrapes Egyptian job Facebook groups for hiring posts.

⚠️  LOCAL ONLY — Facebook blocks datacenter IPs instantly.
     Set SCRAPER_MODE=local in .env to enable.
     DO NOT run on HuggingFace Spaces.

Usage:
    python src/facebook_scraper.py
"""

import os
import re
import time
import uuid
import sys
import subprocess
import platform
import tempfile
import shutil

from dotenv import load_dotenv
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(ROOT_DIR, '.env'))

# Ensure internal src modules like database.py can be imported safely
sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, insert_job

# Runtime mode
SCRAPER_MODE = os.getenv('SCRAPER_MODE', 'production').lower()

# Heuristics
HIRING_PHRASES = [
    'we are hiring', "we're hiring", 'مطلوب', 'وظيفة شاغرة',
    "i'm hiring", 'building my team', 'open position', 'open role',
    'expanding the team', 'now hiring', 'join our team',
    'looking for', 'بنفتش على', 'فرصة عمل', 'نبحث عن',
]

TARGET_GROUPS = [
    'https://www.facebook.com/groups/wzzaif.masr',
    'https://www.facebook.com/groups/DataScienceEgypt',
    'https://www.facebook.com/groups/ITjobsinEgypt',
    'https://www.facebook.com/groups/egypttechjobs',
]


def _get_windows_chrome_file_version(chrome_path: str) -> str | None:
    try:
        out = subprocess.check_output([
            'powershell', '-NoProfile', '-Command', f"(Get-Item \"{chrome_path}\").VersionInfo.FileVersion"
        ], text=True, stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:
        return None


def _get_unix_chrome_version(chrome_path: str) -> str | None:
    for flag in ('--product-version', '--version'):
        try:
            out = subprocess.check_output([chrome_path, flag], text=True, stderr=subprocess.DEVNULL)
            return out.strip()
        except Exception:
            continue
    return None


def _get_chrome_major_version() -> int | None:
    env_path = os.getenv('CHROME_BIN') or os.getenv('CHROME_PATH')
    candidates = [env_path] if env_path else []
    system = platform.system()

    if system == 'Windows':
        candidates.extend([
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ])
    elif system == 'Darwin':
        candidates.append('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    else:
        candidates.extend(['/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium'])

    for chrome_path in candidates:
        if not chrome_path or not os.path.exists(chrome_path):
            continue
        try:
            if system == 'Windows':
                ver = _get_windows_chrome_file_version(chrome_path)
            else:
                ver = _get_unix_chrome_version(chrome_path)
            if not ver:
                continue
            m = re.search(r"(\d+)\.", ver)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def _find_chrome_binary() -> str | None:
    env_path = os.getenv('CHROME_BIN') or os.getenv('CHROME_PATH')
    if env_path and os.path.exists(env_path):
        return env_path

    system = platform.system()
    if system == 'Windows':
        candidates = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]
    elif system == 'Darwin':
        candidates = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    else:
        candidates = ['/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium']

    for chrome_path in candidates:
        if chrome_path and os.path.exists(chrome_path):
            return chrome_path
    return None


def _chrome_running() -> bool:
    try:
        if platform.system() == 'Windows':
            out = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq chrome.exe'], text=True, stderr=subprocess.DEVNULL)
            return 'chrome.exe' in out.lower()
        else:
            out = subprocess.check_output(['pgrep', '-f', 'chrome|chromium'], text=True, stderr=subprocess.DEVNULL)
            return bool(out.strip())
    except Exception:
        return False


def _dismiss_overlays(drv):
    try:
        from selenium.webdriver.common.by import By
    except Exception:
        By = None

    selectors = [
        'button[data-cookiebanner="accept_button"]',
        'button[title*="Allow" i]',
        'button[aria-label*="Accept" i]',
        'div[role="dialog"] button',
        "//button[contains(., 'Accept') or contains(., 'Allow') or contains(., 'OK') or contains(., 'Continue')]",
    ]

    try:
        if By:
            for sel in selectors[:3]:
                try:
                    els = drv.find_elements(By.CSS_SELECTOR, sel)
                    for e in els:
                        try:
                            e.click()
                            time.sleep(0.5)
                        except Exception:
                            try:
                                drv.execute_script('arguments[0].click();', e)
                            except Exception:
                                pass
                except Exception:
                    pass
            try:
                els = drv.find_elements(By.XPATH, selectors[3])
                for e in els:
                    try:
                        e.click()
                        time.sleep(0.5)
                    except Exception:
                        try:
                            drv.execute_script('arguments[0].click();', e)
                        except Exception:
                            pass
            except Exception:
                pass
        try:
            drv.execute_script("[...document.querySelectorAll('div[role=dialog], #cookie-consent')].forEach(n=>n.remove())")
        except Exception:
            pass
    except Exception:
        pass


def _safe_click(driver, element) -> bool:
    try:
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script('arguments[0].click();', element)
            return True
        except Exception:
            return False


def _is_logged_in(driver) -> bool:
    try:
        url = driver.current_url.lower()
        if any(token in url for token in ('login', 'checkpoint', 'recover', 'security')):
            return False
        from selenium.webdriver.common.by import By
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[name="email"], input[id="email"], input[name="pass"], input[id="pass"]')
        return len(inputs) == 0
    except Exception:
        return 'login' not in getattr(driver, 'current_url', '').lower()


def _fill_input(driver, element, value: str):
    try:
        element.clear()
    except Exception:
        pass
    try:
        element.send_keys(value)
    except Exception:
        try:
            driver.execute_script(
                "arguments[0].focus(); arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
                element, value
            )
        except Exception:
            pass


def _attempt_login(driver, fb_email: str, fb_pass: str) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    login_urls = [
        'https://www.facebook.com/login',
        'https://m.facebook.com/login',
        'https://mbasic.facebook.com/login',
    ]
    wait = WebDriverWait(driver, 20)

    for login_url in login_urls:
        try:
            driver.get(login_url)
            time.sleep(3)
            _dismiss_overlays(driver)
            if _is_logged_in(driver):
                return True

            email_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[name="email"], input[id="email"]')
            ))
            pass_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[name="pass"], input[id="pass"]')
            ))

            _fill_input(driver, email_input, fb_email)
            _fill_input(driver, pass_input, fb_pass)

            login_btn = None
            try:
                login_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@name='login' or @type='submit' or contains(., 'Log In') or contains(., 'Log in') or contains(., 'Login') or contains(., 'تسجيل الدخول')]")
                ))
            except Exception:
                pass

            if not login_btn:
                candidates = driver.find_elements(By.CSS_SELECTOR, 'button[name="login"], button[type="submit"], input[type="submit"]')
                login_btn = candidates[0] if candidates else None

            if login_btn and _safe_click(driver, login_btn):
                time.sleep(6)
            else:
                try:
                    driver.execute_script(
                        "const btn = document.querySelector('button[name=\"login\"], button[type=\"submit\"], input[type=\"submit\"]');"
                        "if (btn) btn.click();"
                    )
                    time.sleep(6)
                except Exception:
                    pass

            if _is_logged_in(driver):
                return True
        except Exception:
            continue

    return False


def _normalize_group_url(url: str) -> str:
    if 'facebook.com/groups/' in url and 'mbasic.facebook.com' not in url:
        return url.replace('www.facebook.com', 'mbasic.facebook.com').replace('m.facebook.com', 'mbasic.facebook.com')
    return url


def _is_hiring_post(text: str) -> bool:
    return any(p in text.lower() for p in HIRING_PHRASES)


def _detect_job_type(text: str) -> str:
    t = text.lower()
    if 'remote' in t or 'عن بعد' in t or 'من البيت' in t:
        return 'remote'
    if 'hybrid' in t or 'هجين' in t:
        return 'hybrid'
    return 'onsite'


def _detect_contract(text: str) -> str:
    t = text.lower()
    if 'intern' in t or 'تدريب' in t:
        return 'internship'
    if 'part time' in t or 'دوام جزئي' in t:
        return 'part-time'
    if 'freelance' in t or 'فريلانس' in t:
        return 'contract'
    return 'full-time'


def _extract_title(text: str) -> str:
    ar_match = re.search(r'مطلوب\s+([^\n.،]+)', text)
    if ar_match:
        return ar_match.group(1).strip()[:80]
    en_match = re.search(r'(?:hiring|looking for|seeking)\s+(?:a\s+)?([A-Z][a-zA-Z\s]+(?:Engineer|Scientist|Analyst|Developer|Manager|Intern))', text)
    if en_match:
        return en_match.group(1).strip()
    return 'Job Opportunity'


def run_facebook(groups: list[str] = None, max_posts: int = 30) -> list[dict]:
    if SCRAPER_MODE != 'local':
        print('[Facebook] Skipped — SCRAPER_MODE is not "local". Safe for HuggingFace.')
        return []

    fb_email = os.getenv('FB_EMAIL', '')
    fb_pass = os.getenv('FB_PASS', '')
    if not fb_email or not fb_pass:
        print('[Facebook] FB_EMAIL or FB_PASS not set in .env — skipping.')
        return []

    try:
        import undetected_chromedriver as uc
    except Exception:
        uc = None

    jobs = []
    driver = None
    user_data = None
    user_data_temp = False

    chrome_binary = os.getenv('CHROME_BIN') or os.getenv('CHROME_PATH') or _find_chrome_binary()
    chrome_version_env = os.getenv('CHROME_VERSION')
    use_profile = os.getenv('USE_CHROME_PROFILE', '').lower() in ('1', 'true', 'yes')

    if chrome_binary:
        print(f'[Facebook] using Chrome binary at: {chrome_binary}')
    else:
        print('[Facebook] no Chrome binary path detected; undetected_chromedriver will use defaults')

    if uc:
        opts = uc.ChromeOptions()
        if chrome_binary:
            opts.binary_location = chrome_binary

        if use_profile and platform.system() == 'Windows' and os.path.exists(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')):
            profile_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
            if not _chrome_running():
                print(f'[Facebook] reusing Chrome profile at: {profile_path}')
                opts.add_argument(f'--user-data-dir={profile_path}')
                opts.add_argument('--profile-directory=Default')
            else:
                print('[Facebook] Chrome is running; profile reuse disabled. Using temporary session data.')
                user_data = tempfile.mkdtemp(prefix='fb_ud_')
                user_data_temp = True
                opts.add_argument(f'--user-data-dir={user_data}')
        else:
            user_data = tempfile.mkdtemp(prefix='fb_ud_')
            user_data_temp = True
            opts.add_argument(f'--user-data-dir={user_data}')

        if not (os.getenv('DEBUG_HEADFUL', '') or (SCRAPER_MODE == 'local')):
            opts.add_argument('--headless=new')

        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_argument('--window-size=1280,900')

    try:
        if uc:
            version_main = None
            if chrome_version_env:
                try:
                    version_main = int(chrome_version_env.split('.')[0])
                except Exception:
                    version_main = None
            else:
                version_main = _get_chrome_major_version()

            if version_main:
                print(f'[Facebook] detected local Chrome major version: {version_main}')
                driver = uc.Chrome(options=opts, version_main=version_main, browser_executable_path=chrome_binary)
            else:
                print('[Facebook] launching undetected_chromedriver default')
                driver = uc.Chrome(options=opts, browser_executable_path=chrome_binary)
        else:
            raise RuntimeError('undetected_chromedriver not available')

    except Exception as primary_err:
        print(f'[Facebook] primary driver start failed: {primary_err}')
        try:
            if user_data_temp and user_data and os.path.exists(user_data):
                shutil.rmtree(user_data)
        except Exception:
            pass

        chromedriver_env = os.getenv('CHROMEDRIVER_PATH')
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
        except Exception as imp_err:
            print(f'[Facebook] selenium not installed: {imp_err} — run pip install selenium')
            return []

        selenium_opts = webdriver.ChromeOptions()
        if chrome_binary:
            selenium_opts.binary_location = chrome_binary
        selenium_opts.add_argument('--headless=new')
        selenium_opts.add_argument('--no-sandbox')
        selenium_opts.add_argument('--disable-dev-shm-usage')
        selenium_opts.add_argument('--disable-blink-features=AutomationControlled')
        selenium_opts.add_argument('--window-size=1280,900')

        try:
            if chromedriver_env and os.path.exists(chromedriver_env):
                service = Service(chromedriver_env)
                driver = webdriver.Chrome(service=service, options=selenium_opts)
                print('[Facebook] started selenium with CHROMEDRIVER_PATH')
            else:
                try:
                    import chromedriver_autoinstaller
                except Exception:
                    print('[Facebook] installing chromedriver_autoinstaller...')
                    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'chromedriver_autoinstaller'])
                    import chromedriver_autoinstaller

                chromedriver_path = chromedriver_autoinstaller.install()
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=selenium_opts)
                print('[Facebook] started selenium with chromedriver_autoinstaller')

        except Exception as fallback_err:
            print(f'[Facebook] fallback selenium start failed: {fallback_err}')
            return []

    # run the browsing and scraping logic
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except Exception:
        print('[Facebook] selenium support imports failed')

    try:
        print('[Facebook] Navigating to Facebook...')
        driver.get('https://www.facebook.com/')
        time.sleep(3)
        _dismiss_overlays(driver)

        if use_profile and _is_logged_in(driver):
            print('[Facebook] already logged in via reused profile')
        else:
            print('[Facebook] attempting login...')
            success = _attempt_login(driver, fb_email, fb_pass)
            if not success:
                print('[Facebook] login attempt failed; some groups may require an active session')
            else:
                print('[Facebook] login successful')

        target = groups or TARGET_GROUPS
        for group_url in target:
            normalized_url = _normalize_group_url(group_url)
            print(f'[Facebook] Scraping: {normalized_url}')
            driver.get(normalized_url)
            time.sleep(4)

            for _ in range(5):
                driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
                time.sleep(2)

            try:
                for more in driver.find_elements(By.XPATH, "//a[contains(text(),'See more') or contains(text(),'عرض المزيد') or contains(text(),'See More')]"):
                    _safe_click(driver, more)
                    time.sleep(0.3)
            except Exception:
                pass

            posts = []
            try:
                posts = (driver.find_elements(By.CSS_SELECTOR, 'div[role="article"]')
                         or driver.find_elements(By.CSS_SELECTOR, 'div[data-sigil="m-feed-item"]')
                         or driver.find_elements(By.CSS_SELECTOR, 'div[data-sigil="feed-ufi"]')
                         or driver.find_elements(By.CSS_SELECTOR, '.userContent'))
            except Exception:
                pass

            for post in (posts or [])[:max_posts]:
                try:
                    text = post.text or post.get_attribute('innerText') or ''
                    text = text.strip()
                    if not text or not _is_hiring_post(text):
                        continue
                    try:
                        link_el = post.find_element(By.CSS_SELECTOR, 'a[href*="/groups/"][href*="/posts/"]')
                        post_url = link_el.get_attribute('href')
                    except Exception:
                        post_url = normalized_url

                    jobs.append({
                        'source_id': f'fb_{uuid.uuid4().hex[:10]}',
                        'title': _extract_title(text),
                        'company': 'Unknown',
                        'location': 'Egypt',
                        'country': 'Egypt',
                        'job_type': _detect_job_type(text),
                        'contract_type': _detect_contract(text),
                        'salary_min': None,
                        'salary_max': None,
                        'description': text[:2000],
                        'source': 'facebook',
                        'source_url': post_url,
                        'raw_post_text': text,
                    })
                except Exception:
                    continue

            try:
                page_html = driver.page_source
                alt = '|'.join(re.escape(p) for p in HIRING_PHRASES)
                pattern = re.compile(rf'(.{{0,400}}(?:{alt}).{{0,800}})', re.IGNORECASE | re.DOTALL)
                matches = pattern.findall(page_html)
                print(f'[Facebook] regex found {len(matches)} candidate text blocks in page source')
                for m in matches:
                    text = re.sub(r'\s+', ' ', m).strip()
                    if not _is_hiring_post(text):
                        continue
                    if any(text in j.get('raw_post_text', '') for j in jobs):
                        continue
                    jobs.append({
                        'source_id': f'fb_{uuid.uuid4().hex[:10]}',
                        'title': _extract_title(text),
                        'company': 'Unknown',
                        'location': 'Egypt',
                        'country': 'Egypt',
                        'job_type': _detect_job_type(text),
                        'contract_type': _detect_contract(text),
                        'salary_min': None,
                        'salary_max': None,
                        'description': text[:2000],
                        'source': 'facebook',
                        'source_url': normalized_url,
                        'raw_post_text': text,
                    })
            except Exception as regex_err:
                print(f'[Facebook] page-source regex fallback failed: {regex_err}')

            time.sleep(2)

    except Exception as e:
        print(f'[Facebook] scraper error: {e}')
    finally:
        try:
            if driver:
                driver.quit()
        except Exception as teardown_err:
            print(f'[Facebook] Driver cleanup error: {teardown_err}')
        finally:
            driver = None

        try:
            if user_data_temp and user_data and os.path.exists(user_data):
                time.sleep(1)
                try:
                    shutil.rmtree(user_data)
                except Exception:
                    time.sleep(0.5)
                    try:
                        shutil.rmtree(user_data)
                    except Exception as rm_err:
                        print(f'[Facebook] failed to remove user-data-dir: {rm_err}')
        except Exception as rm_err:
            print(f'[Facebook] failed to remove user-data-dir: {rm_err}')

    print(f'[Facebook] found {len(jobs)} hiring posts')
    return jobs


def run():
    if SCRAPER_MODE != 'local':
        print('[Facebook] Production mode — skipping Facebook scraper.')
        return 0

    init_db()
    jobs = run_facebook()
    saved = sum(1 for j in jobs if insert_job(j))
    print(f'[Facebook] saved {saved}/{len(jobs)} posts.')
    return saved


if __name__ == '__main__':
    run()
