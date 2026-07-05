# JobHunter — Complete Project Documentation
> **v3.0 — Week 2 complete ✅**
> Save this file. Everything you need to continue is here.

---

## Project identity

- **Name:** JobHunter
- **Type:** AI-Powered Job Market Intelligence Platform
- **Developer:** Hazem Mohammad Salah
- **Stack:** Python · Flask · Pandas · Scikit-learn · LangChain · ChromaDB · Groq API · Power BI · HuggingFace Spaces

---

## Elevator pitch

Full-stack AI platform that collects jobs from APIs + social media posts ("We are hiring"), extracts skills via NLP, recommends jobs by skill matching, and answers career questions via RAG chatbot — auto-refreshing in the background, deployed on HuggingFace Spaces.

---

## Current status

| Week | Focus | Status |
|---|---|---|
| 1 | Data pipeline + ETL + Streamlit MVP | ✅ Done |
| 2 | Flask UI + NLP + social scraper + auto-refresh | ✅ Done |
| 3 | Salary prediction + experience level extraction | 📋 Next |
| 4 | RAG career assistant (ChromaDB + LangChain + Groq) | 📋 Planned |
| 5 | CV analyzer (PDF → ATS score) + Power BI export | 📋 Planned |
| 6 | Polish + Docker + HuggingFace Spaces deployment | 📋 Planned |

---

## Project structure

```
jobhunter/
├── data/
│   └── jobs.db
├── src/
│   ├── database.py          ← DB schema + CRUD + get_stats()
│   ├── pipeline.py          ← Adzuna API fetcher (--keywords --country --pages)
│   ├── etl.py               ← Text cleaning + TF-IDF skill extraction
│   ├── recommender.py       ← KNN recommender (country_filter, job_type_filter)
│   ├── nlp_analysis.py      ← Word cloud, KMeans clusters, skill trends, co-occurrence
│   ├── social_scraper.py    ← Twitter/X API + LinkedIn Selenium scraper
│   └── scheduler.py         ← APScheduler auto-refresh (every N hours)
├── app/
│   ├── __init__.py          ← Flask app factory (init_db + register routes + start scheduler)
│   ├── routes.py            ← All URL routes + REST API endpoints
│   ├── templates/
│   │   ├── base.html        ← Navbar, Tailwind, Plotly, dark theme
│   │   ├── index.html       ← Dashboard (KPI cards + charts)
│   │   ├── jobs.html        ← Filterable job grid
│   │   ├── recommend.html   ← Skills input → ranked job cards
│   │   └── analytics.html   ← Word cloud, clusters, trends, co-occurrence, salary
│   └── static/
│       ├── css/style.css    ← Custom Tailwind component classes
│       └── js/main.js       ← Auto-submit filters on change
├── run.py                   ← python run.py → Flask on :5000
├── requirements.txt
└── env.example
```

---

## Database schema (current)

```sql
companies   (id PK, name UNIQUE)

jobs        (id PK, source_id UNIQUE, title, company_id FK,
             location, country,
             job_type      TEXT  -- onsite | remote | hybrid
             contract_type TEXT  -- full-time | part-time | internship | contract
             salary_min, salary_max, description,
             source        TEXT  -- adzuna | social_twitter | social_linkedin | manual
             source_url,
             raw_post_text TEXT  -- original social post text
             scraped_at)

skills      (id PK, name UNIQUE, category)
job_skills  (job_id FK, skill_id FK, tfidf_score, PRIMARY KEY(job_id, skill_id))
```

### Future tables (Week 4+)
```sql
users       (id PK, name, email, cv_text, created_at)
user_skills (user_id FK, skill_id FK, proficiency)
recommendations (id PK, user_id FK, job_id FK, match_score, created_at)
```

---

## Environment variables (.env)

```env
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
TWITTER_BEARER_TOKEN=your_token
LINKEDIN_EMAIL=your_email
LINKEDIN_PASS=your_password
REFRESH_HOURS=6
SECRET_KEY=any_random_string
```

---

## Setup

```bash
pip install -r requirements.txt
cp env.example .env   # fill in keys

# Fetch jobs
python src/pipeline.py --keywords "data scientist" --country gb --pages 5
python src/pipeline.py --keywords "data scientist" --country us --pages 5
python src/pipeline.py --keywords "intern data" --country gb --pages 3

# Extract skills
python src/etl.py

# Run social scraper
python src/social_scraper.py

# Launch
python run.py   # → http://localhost:5000
```

---

## Flask routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Dashboard — KPIs + charts |
| `/jobs` | GET | Job grid with filters (country, job_type, contract_type, search) |
| `/recommend` | GET/POST | Skills input → ranked job cards |
| `/analytics` | GET | Word cloud, clusters, skill trends, co-occurrence, salary |
| `/api/jobs` | GET | JSON list of jobs (filterable) |
| `/api/recommend` | POST | JSON recommender `{skills, top_n, country, job_type}` |
| `/api/stats` | GET | JSON DB stats |
| `/api/refresh` | POST | Trigger background refresh manually |

---

## Key modules — what each does

### `social_scraper.py`
Searches Twitter/X + LinkedIn for posts containing:
`"we are hiring"`, `"i'm hiring"`, `"building my team"`, `"expanding the team"`,
`"we're growing"`, `"know anyone great for"`, `"looking for someone"`, etc.

Extracts: title (regex), job_type (remote/hybrid/onsite from text), contract_type (intern/contract/etc)
Stores in `jobs` table with `source = 'social_twitter'` or `'social_linkedin'`

Requires: `TWITTER_BEARER_TOKEN` for Twitter, `LINKEDIN_EMAIL+PASS` for LinkedIn (Selenium)

### `scheduler.py`
APScheduler background thread — runs every `REFRESH_HOURS` hours:
1. `pipeline.run()` for each country × keyword combo
2. `etl.run_etl()` to extract skills from new jobs
3. `social_scraper.run()` for new social posts

`trigger_now()` available for manual refresh via `/api/refresh`

### `nlp_analysis.py`
- `generate_wordcloud()` → base64 PNG
- `cluster_jobs(n=5)` → KMeans scatter data + cluster counts
- `skill_trends()` → top 25 skills with category
- `skill_cooccurrence(n=15)` → heatmap matrix
- `country_salary_heatmap()` → avg salary by country

### `recommender.py`
KNN with cosine similarity on TF-IDF skill vectors.
Accepts `country_filter` and `job_type_filter` — country toggle feature ready.

---

## Country filter feature

**Status:** 95% done. Just needs multi-country data.

```bash
# Populate 3+ countries then the UI toggle works automatically
python src/pipeline.py --keywords "data scientist" --country us --pages 5
python src/pipeline.py --keywords "data scientist" --country ae --pages 3
python src/pipeline.py --keywords "data scientist" --country de --pages 3
```

The `/jobs` and `/recommend` pages already have country dropdowns auto-populated from DB.

---

## Unique features (differentiators)

1. ✅ **Social "We are hiring" scraper** — catches unlisted jobs nobody else has
2. ✅ **Auto-refresh** — always fresh data, scheduler runs in background
3. ✅ **Internship track** — separate contract_type with dedicated filter
4. 📋 **CV ↔ Job matcher** — upload PDF → ATS score + missing skills (Week 5)
5. 📋 **Skills demand forecasting** — Prophet/ARIMA trends (Week 3)
6. 📋 **Egypt salary heatmap** — choropleth by governorate (Week 5)
7. 📋 **AI interview simulator** — LLM per job description (Week 4)
8. 📋 **Career gap analyzer** — target role → skill gap → roadmap (Week 4)

---

## Week 3 plan (next)

### Salary prediction model
- Feature engineering: `skills`, `country`, `job_type`, `contract_type`, `seniority_level`
- Model: `GradientBoostingRegressor` (better than plain Regression for this)
- Evaluation: MAE, R² with cross-validation
- Output: salary range estimate shown in recommender results

### Experience level extraction
- Extract from description: `junior | mid | senior | lead` via regex + keyword matching
- Store as `seniority` column in `jobs` table
- Add seniority filter to `/jobs` and `/recommend` pages

### Improve recommender
- Upgrade from raw TF-IDF to `sentence-transformers` (multilingual-e5-base — same as Efteely)
- Better semantic matching (e.g. "NLP" matches "natural language processing")

---

## Reuse from Efteely (Week 4 RAG)

| Efteely | JobHunter RAG layer |
|---|---|
| ChromaDB `/tmp/chroma_db` on HF Spaces | Same pattern |
| `intfloat/multilingual-e5-base` embeddings | Same |
| Groq API + llama-3.3-70b-versatile | Same |
| LangChain RAG chain | Adapt for career queries |
| Intent detection router | career vs chitchat |

HF dataset ref: `H-Salah/online-efteely-chroma`

---

## Full tech stack

```
Backend:        Python, Flask
Data:           Pandas, NumPy, SQLite
Scheduling:     APScheduler
ML/NLP:         Scikit-learn, TF-IDF, KMeans, Sentence Transformers, KNN, GBR
GenAI:          LangChain, ChromaDB, Groq API (llama-3.3-70b-versatile)
Embeddings:     intfloat/multilingual-e5-base
Scraping:       Requests, Selenium (undetected-chromedriver), Tweepy
Frontend:       Jinja2, Tailwind CSS (CDN), Plotly.js
BI:             Power BI, Plotly
Deployment:     HuggingFace Spaces, Docker, GitHub
```

---

*Last updated: May 2026 — Week 2 complete.*
