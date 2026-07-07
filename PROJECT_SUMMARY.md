# JobHunter — Complete Project Reference
> **Read this file first.** Self-contained reference for the entire project. Last updated: 2026-07-05.

---

## 1. Project Overview

**JobHunter** is a Flask web application that:
- Scrapes AI/Data Science job listings from multiple sources (Adzuna, Wuzzuf, LinkedIn, Facebook, JobSpy)
- Stores jobs in SQLite with NLP-extracted skills + TF-IDF weights
- Recommends jobs to users via KNN cosine similarity on a skill pivot matrix
- Rates uploaded CVs with an ATS scorecard + LLM semantic analysis
- Includes a Hugging Face LLM-powered career coach chatbot (RAG with ChromaDB)
- Provides a bilingual (EN/AR) dashboard with Plotly analytics charts

**Deployed target:** Hugging Face Spaces (free tier, CPU-only). **No Groq dependency** — all LLM calls now route via `HF_TOKEN` (serverless Hugging Face Inference API) or fall back to loading `Qwen/Qwen2.5-0.5B-Instruct` locally.

---

## 2. Repository Layout

```
JobHunter/
├── run.py                     # Entry point — starts Flask on 0.0.0.0:5000
├── requirements.txt           # Python deps (no groq; has huggingface_hub, transformers, torch)
├── .env                       # Secrets (Adzuna keys, HF_TOKEN, SECRET_KEY)
├── PROJECT_SUMMARY.md         # THIS FILE — quick context for AI assistants
├── data/
│   ├── jobs.db                # SQLite database
│   └── chroma_db/             # ChromaDB vector store
├── models/                    # Persisted ML model files (salary, seniority)
├── app/
│   ├── __init__.py            # Flask factory, registers blueprint, starts scheduler
│   ├── routes.py              # All Flask routes (Blueprint: main)
│   ├── translations.py        # Bilingual string dictionary (EN/AR)
│   └── templates/
│       ├── base.html          # Layout: navbar, dark/light toggle, chatbot modal
│       ├── index.html         # Dashboard + embedded analytics (7 Plotly charts)
│       ├── jobs.html          # Job listings with filters + pagination (21/page)
│       ├── recommend.html     # 3-tab recommender: Manual | Rate CV | Make CV
│       ├── 404.html           # Custom 404 page
│       └── 500.html           # Custom 500 page
│   └── static/
│       └── style.css          # All CSS — vanilla, dark/light tokens, glassmorphism
└── src/
    ├── database.py            # SQLite schema + CRUD helpers
    ├── etl.py                 # Extract skills, run TF-IDF, update job_skills table
    ├── pipeline.py            # Orchestrates scrape → clean → insert per keyword/country
    ├── recommender.py         # KNN recommendation engine + pivot matrix cache
    ├── nlp_analysis.py        # WordCloud, clustering, trends, co-occurrence
    ├── rag_assistant.py       # ChromaDB indexing + HF LLM calls (chat, summarize, ATS)
    ├── ats_evaluator.py       # Deterministic ATS scoring rules
    ├── cv_parser.py           # Extracts text from PDF/DOCX
    ├── salary_model.py        # Trains + uses ML salary predictor
    ├── scheduler.py           # APScheduler: auto-refresh every 6h, backfill every 15m
    ├── wuzzuf_scraper.py      # Wuzzuf scraper (Selenium)
    ├── facebook_scraper.py    # Facebook scraper (Selenium, local mode only)
    ├── linkedin_scraper.py    # LinkedIn scraper (Selenium, local mode only)
    ├── jobspy_scraper.py      # JobSpy multi-site scraper
    └── social_scraper.py      # Lightweight wrapper for social scrapers
```

---

## 3. Environment Variables (.env)

| Variable | Purpose |
|---|---|
| `ADZUNA_APP_ID` | Adzuna API ID |
| `ADZUNA_APP_KEY` | Adzuna API key |
| `ADZUNA_COUNTRY` | Default country code (e.g. `gb`) |
| `ADZUNA_DEFAULT_QUERY` | Default search term |
| `SCRAPER_MODE` | `local` (all scrapers) or `production` (Adzuna + Wuzzuf only) |
| `FB_EMAIL` / `FB_PASS` | Facebook credentials (local mode only) |
| `REFRESH_HOURS` | Auto-refresh interval (default `6`) |
| `SECRET_KEY` | Flask session secret |
| `HF_TOKEN` or `HF_API_TOKEN` | Hugging Face token — enables serverless Inference API |
| `HF_API_MODEL_CHAT` | API model for chat / coaching (default: `Qwen/Qwen2.5-72B-Instruct`) |
| `HF_API_MODEL_SUMMARY` | API model for summarization (default: `meta-llama/Llama-3.2-3B-Instruct`) |
| `HF_LOCAL_MODEL_CHAT` | Local model for chat (default: `Qwen/Qwen2.5-0.5B-Instruct`) |
| `HF_LOCAL_MODEL_SUMMARY` | Local model for summarization (default: `Qwen/Qwen2.5-0.5B-Instruct`) |
| `GROQ_API_KEY` (legacy) | No longer used by the app — can be removed |

---

## 4. SQLite Database Schema (data/jobs.db)

```sql
companies (id, name UNIQUE)

jobs (
  id, source_id UNIQUE, title, company_id -> companies,
  location, country, job_type, contract_type,
  salary_min, salary_max,
  description, source, source_url, raw_post_text,
  seniority, summary_en, summary_ar,
  posted_at, scraped_at
)

skills (id, name UNIQUE, category)

job_skills (job_id -> jobs, skill_id -> skills, tfidf_score, PRIMARY KEY(job_id, skill_id))
```

---

## 5. Flask Routes (app/routes.py)

| Method | Route | Handler | Description |
|---|---|---|---|
| GET | `/` | `index()` | Dashboard: stats KPIs + 7 Plotly charts |
| GET | `/jobs` | `jobs()` | Job listings, filters, pagination (21/page) |
| GET/POST | `/recommend` | `recommend_jobs()` | 3-tab recommender page |
| GET | `/analytics` | `analytics()` | Redirects to `/#analytics` |
| GET | `/api/jobs` | `api_jobs()` | JSON job list (filterable) |
| POST | `/api/recommend` | `api_recommend()` | JSON skill-based recommendations |
| GET | `/api/stats` | `api_stats()` | JSON dashboard stats |
| POST | `/api/refresh` | `api_refresh()` | Triggers background ETL refresh |
| POST | `/api/salary-predict` | `api_salary_predict()` | Salary prediction JSON |
| GET | `/api/health` | `api_health()` | Health check |
| POST | `/api/chat` | `api_chat()` | Chatbot endpoint (RAG + HF LLM) |
| GET | `/change-lang/<lang>` | `change_lang()` | Switches session language (en/ar) |

---

## 6. Key Source Files — Logic Summary

### src/database.py
- `get_connection()` — SQLite connection with `row_factory = sqlite3.Row`
- `init_db()` — creates tables + safe migrations (safe to re-run)
- `insert_job(job_dict)` — upserts by `source_id`
- `fetch_all_jobs(country, job_type, contract_type, seniority, search_query, limit)` — SQL LIKE filtering
- `get_stats()` — returns dict: `total_jobs, remote_count, internship_count, company_count, countries_count, social_count`
- `get_filter_options()` — SQL DISTINCT for countries, seniorities
- `insert_skill(name, conn=None)` / `insert_job_skill(job_id, skill_id, score, conn=None)` — accept shared connection for batch ETL

### src/etl.py
- `run_etl()` — single transaction: reads all jobs, TF-IDF skill extraction, bulk-inserts to `job_skills`
- Single `get_connection()` for the whole ETL run (fixed the N x 5000 open/close bug)

### src/recommender.py
- `recommend(skills_list, top_n, country_filter, job_type_filter, contract_type_filter, seniority_filter)` — KNN cosine similarity
- `load_job_skill_matrix()` — builds pivot DataFrame; cached in `_MATRIX_CACHE` for 60 seconds
- `get_top_skills(n)` — most frequent skills
- `get_salary_stats()` — salary range stats

### src/rag_assistant.py
- **Embedding model:** `intfloat/multilingual-e5-base` (SentenceTransformer) — prefix "query: " / "passage: "
- **Vector store:** ChromaDB persistent at `data/chroma_db/`, collection `jobhunter_jobs`, cosine similarity
- `index_new_jobs(reindex=False)` — syncs SQLite jobs to ChromaDB, prunes >30-day-old entries
- `search_jobs(query_text, limit=4)` — semantic nearest-neighbor search
- **LLM routing** via `_get_hf_client_or_pipeline(model_type)`:
  - Supports separated models for `chat` and `summary` with caching per model name.
  - HF_TOKEN found -> `InferenceClient` (serverless, default chat: `Qwen/Qwen2.5-72B-Instruct`, summary: `meta-llama/Llama-3.2-3B-Instruct`)
  - No token -> loads locally (default: `Qwen/Qwen2.5-0.5B-Instruct`) (NO `device_map="auto"` — no `accelerate` needed)
- `_call_llm_hf(messages, temperature, max_tokens, json_mode)` — unified LLM wrapper
- `chat_with_coach(user_message, chat_history)` — RAG chatbot with Egyptian Arabic slang instruction
- `summarize_description(description)` — returns `(summary_en, summary_ar)` as JSON tuple
- `analyze_cv_for_ats(cv_text)` — runs local ATS + LLM for missing skills + bilingual summary
- Backward-compat stubs: `set_summary_backoff()`, `get_summary_backoff()`, `is_summary_backed_off()` (all no-ops)

### src/ats_evaluator.py
- `evaluate_resume_ats(cv_text)` — deterministic rule-based scoring
- Returns: `{ ats_score, detected_skills, feedback_en, feedback_ar }`

### src/cv_parser.py
- `extract_cv_text(file_bytes, filename)` — handles PDF (PyPDF2) and DOCX (python-docx)

### src/salary_model.py
- Trains Random Forest on jobs with real salary data
- `predict_salary(title, description, country, job_type, contract_type)` — returns `{salary_min, salary_max}`
- `update_job_seniority()` — batch-updates the `seniority` column for newly scraped jobs

### src/scheduler.py
- `start()` — APScheduler BackgroundScheduler with two jobs:
  - `_refresh_job()` every `REFRESH_HOURS` hours: pipeline scrape + ETL + seniority + ChromaDB sync
  - `_auto_backfill_summaries_job()` every 15 minutes: summarizes jobs missing `summary_en`/`summary_ar`
- `trigger_now()` — manually fires `_refresh_job()` in a daemon thread
- `get_last_run()` — ISO timestamp of last completed refresh

### src/nlp_analysis.py
- `get_analytics_data()` — cached; returns wordcloud_b64, clusters, trends, co-occurrence, salary data
- `cluster_jobs()` — KMeans on TF-IDF job descriptions
- `skill_trends()` — rolling monthly skill count
- `skill_cooccurrence()` — co-occurrence matrix for heatmap
- `contract_type_breakdown()` — pie chart data
- `generate_wordcloud()` — base64 PNG

---

## 7. Frontend Structure

### app/templates/base.html
- Navbar: Dashboard | Jobs | Recommend + EN/AR language switcher + dark/light theme toggle
- Floating chatbot bubble -> slide-up modal -> calls `/api/chat` via fetch
- `t(key)` Jinja2 function (from translations.py inlined in template)
- CSS: `app/static/style.css` — vanilla CSS, CSS custom properties, dark/light mode, glassmorphism

### app/templates/index.html
- Hero section with Refresh button (`triggerRefresh(this)`)
- 6 KPI cards (`.kpi-card`, `.stagger-in` animation)
- 7 Plotly charts (rendered from JSON passed by routes.py):
  1. Top Skills bar (horizontal)
  2. Contract Type pie
  3. Job Cluster scatter
  4. Skill Trends line
  5. Co-occurrence heatmap
  6. Seniority breakdown bar
  7. Avg Salary by Seniority bar
- Word cloud image (base64 inline `<img>`)
- `themeChanged` event listener updates all Plotly chart colors

### app/templates/jobs.html
- Filters form class `auto-submit` (GET /jobs): country, job_type, contract_type, seniority, search
- Job cards (`.job-card`, `.stagger-in`): title, company, badges, salary (real or ML-predicted), collapsible description
- Pagination (`.pagination`, `.page-btn`), 21 jobs per page

### app/templates/recommend.html (largest file — 47KB)
- **Tab 1 — Manual Input:** skills textarea + filters -> POST /recommend
- **Tab 2 — Rate CV & Match:** file dropzone (PDF/DOCX, max 5MB) -> POST multipart /recommend
  - Shows ATS score ring, detected skills, missing skills, bilingual feedback
- **Tab 3 — Make CV:** full LaTeX CV builder form
  - Fields: name, title, email, phone, location, LinkedIn, GitHub, summary, skills, experience, education
  - Client-side LaTeX generation -> PDF preview via html2pdf.js
  - Buttons: Download PDF, Download .tex (Blob URL), Copy LaTeX code (with insecure-context fallback)
  - Layout: full-width while editing, 2-col after compile

---

## 8. Data Pipeline Flow

```
Scrapers (Adzuna / Wuzzuf / JobSpy / LinkedIn)
    |
    v
pipeline.py -> insert_job() -> jobs table (SQLite)
    |
    v
etl.py -> TF-IDF -> job_skills table (single transaction)
    |
    v
salary_model.py -> update_job_seniority()
    |
    v
rag_assistant.index_new_jobs() -> ChromaDB (SentenceTransformer embeddings)
    |
    v (background scheduler, every 15 min)
rag_assistant.summarize_description() -> HF LLM -> summary_en / summary_ar
```

---

## 9. Recommendation Engine

```python
user_skills_vector = binary 1D vector over all known skills
job_skill_matrix   = pivot(job_id x skill_id, values=tfidf_score)  # 60s TTL cache
similarities       = cosine_similarity(user_vector, job_skill_matrix)
top_n results      = sorted desc by similarity, filtered by country/type/seniority
```

---

## 10. RAG Chatbot Flow

```
user_message
    -> SentenceTransformer encode ("query: {msg}")
    -> ChromaDB query -> top-4 matching jobs (cosine distance < 0.85)
    -> Build system prompt with job context + Egyptian Arabic persona instruction
    -> _call_llm_hf(messages) -> HF serverless or local Qwen
    -> Return text response to chat modal
```

---

## 11. ATS CV Rating Flow

```
CV upload (PDF/DOCX, <= 5MB)
    -> cv_parser.extract_cv_text()
    -> ats_evaluator.evaluate_resume_ats() -> deterministic score + feedback
    -> rag_assistant.analyze_cv_for_ats()
        -> _call_llm_hf(prompt, json_mode=True)
        -> parse JSON: { missing_skills[], summary_en, summary_ar }
    -> merge deterministic + LLM results
    -> render recommend.html with ats_analysis dict
```

---

## 12. Key Design Decisions & Constraints

| Topic | Decision |
|---|---|
| LLM backend | Hugging Face only (no Groq). HF_TOKEN -> serverless API; no token -> local Qwen2.5-0.5B |
| No accelerate needed | `device_map="auto"` removed; model loaded with torch.float32, moved to CUDA if available |
| SQLite locking | ETL runs in one shared connection + single BEGIN/COMMIT transaction |
| Search performance | SQL LIKE filtering in `fetch_all_jobs()` — no Python-side filtering |
| Pivot matrix caching | `_MATRIX_CACHE` dict with 60s TTL prevents repeated heavy pivot builds |
| File upload validation | Extension check (.pdf, .docx) + 5MB size limit in route before processing |
| Copy to clipboard | `navigator.clipboard.writeText` with `execCommand('copy')` fallback for HTTP contexts |
| Analytics page | No separate page — embedded in index.html; `/analytics` redirects to `/#analytics` |
| CSS | Pure vanilla CSS, no Tailwind. CSS custom properties for theming (--bg, --card, --accent, etc.) |
| Translations | translations.py dict, t(key) Jinja2 function, session lang = en/ar |
| Error pages | 404.html and 500.html registered as error handlers in app/__init__.py |
| Logging | Standard `logging` module throughout — no print() statements |
| Scraper mode | SCRAPER_MODE=production disables LinkedIn/Facebook Selenium scrapers for HF Spaces |

---

## 13. Known Issues & Watchouts

- **NumPy version warning:** scipy wants numpy >=1.26.4 but 1.26.3 is installed. Non-breaking, just a warning.
- **Transformers lazy loading:** First LLM call (no HF_TOKEN) takes 40-60 seconds for model download + init. Subsequent calls use the cached `_hf_pipeline` global.
- **Scheduler race on startup:** `_auto_backfill_summaries_job` fires immediately on startup. The global `_hf_pipeline` cache prevents duplicate model loads.
- **SQLite concurrent writes:** Heavy scheduler traffic can trigger `database is locked`. Consider `PRAGMA journal_mode=WAL` for production.
- **SCRAPER_MODE=local in .env:** Currently set to `local` (launches Selenium). Change to `production` before deploying to HF Spaces.
- **Groq keys in .env:** `GROQ_API_KEY` and `GROQ_CHAT_API_KEY` still present but ignored. Safe to leave or remove.

---

## 14. Deployment Checklist (Hugging Face Spaces)

1. Set `SCRAPER_MODE=production` in Space secrets
2. Add `HF_TOKEN` to Space secrets for serverless LLM
3. Optionally set `HF_API_MODEL=Qwen/Qwen2.5-72B-Instruct` (default)
4. Remove Groq keys or leave (app ignores them)
5. Pre-populate `data/jobs.db` or let the first scheduled refresh fill it
6. Set `REFRESH_HOURS=6` (or desired interval)
7. `requirements.txt` is complete — no extra installs needed

---

## 15. Quick Code Locations

| What you want to change | File |
|---|---|
| Add a new Flask route | `app/routes.py` |
| Change DB schema | `src/database.py` -> `init_db()` |
| Change recommendation algorithm | `src/recommender.py` -> `recommend()` |
| Change LLM model or prompts | `src/rag_assistant.py` -> `_get_hf_client_or_pipeline()`, `chat_with_coach()`, `summarize_description()`, `analyze_cv_for_ats()` |
| Change ATS scoring rules | `src/ats_evaluator.py` |
| Add/edit translation strings | `app/translations.py` |
| Change dashboard charts | `app/templates/index.html` (Plotly JS blocks) |
| Change jobs page filters | `app/templates/jobs.html` + `src/database.py` -> `fetch_all_jobs()` |
| Change recommender page tabs | `app/templates/recommend.html` |
| Change CSS design tokens | `app/static/style.css` -> `:root {}` block |
| Change auto-refresh schedule | `src/scheduler.py` -> `start()` |
| Change scraping sources/keywords | `src/scheduler.py` -> `SEARCH_KEYWORDS` / `COUNTRIES` |
