\# Job Market AI — MVP



A smart job market intelligence platform with NLP-powered skill extraction and job recommendations.



\## Project structure



```

job\_market\_ai/

├── data/

│   └── jobs.db              # SQLite database (auto-created)

├── src/

│   ├── pipeline.py          # Data collection from Adzuna API

│   ├── etl.py               # Cleaning + skill extraction

│   ├── recommender.py       # KNN-based job recommender

│   └── database.py          # DB helpers

├── app.py                   # Streamlit UI

├── requirements.txt

└── .env.example

```



\## Setup



```bash

pip install -r requirements.txt

cp .env.example .env

\# Add your Adzuna API keys to .env

streamlit run app.py

```



\## Feature roadmap



\- \[x] Adzuna API data collection

\- \[x] ETL pipeline (clean, normalize, extract skills)

\- \[x] SQLite storage

\- \[x] TF-IDF skill extraction

\- \[x] KNN job recommender

\- \[x] Streamlit dashboard

\- \[ ] Country filter toggle (local vs remote jobs) — \*planned\*

\- \[ ] Salary prediction model

\- \[ ] RAG career assistant

\- \[ ] CV analyzer + ATS score

\- \[ ] Power BI dashboard export

