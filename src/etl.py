"""
etl.py — cleans job descriptions and extracts skills using TF-IDF + a curated skill list.

Usage:
    python src/etl.py
"""

import re
import sqlite3
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from database import get_connection, insert_skill, insert_job_skill, DB_PATH

# Curated tech + soft skill list (extend this freely)
KNOWN_SKILLS = {
    # Languages
    'python', 'sql', 'r', 'java', 'scala', 'javascript', 'typescript',
    'c++', 'c#', 'go', 'rust', 'bash',
    # Data / ML
    'pandas', 'numpy', 'scikit-learn', 'pytorch', 'tensorflow', 'keras',
    'xgboost', 'lightgbm', 'spark', 'hadoop', 'dbt', 'airflow',
    'mlflow', 'dvc', 'feature engineering', 'eda',
    # NLP / GenAI
    'nlp', 'transformers', 'hugging face', 'langchain', 'rag',
    'llm', 'openai', 'gpt', 'bert', 'spacy', 'nltk',
    # Databases
    'postgresql', 'mysql', 'sqlite', 'mongodb', 'redis',
    'elasticsearch', 'chromadb', 'pinecone', 'snowflake', 'bigquery',
    # Cloud / DevOps
    'aws', 'gcp', 'azure', 'docker', 'kubernetes', 'terraform',
    'ci/cd', 'github actions',
    # BI / Viz
    'power bi', 'tableau', 'looker', 'matplotlib', 'seaborn', 'plotly', 'dash',
    # Soft skills
    'communication', 'teamwork', 'problem solving', 'leadership',
    'agile', 'scrum',
}

SKILL_CATEGORIES = {
    'python': 'language', 'sql': 'language', 'r': 'language',
    'java': 'language', 'scala': 'language', 'javascript': 'language',
    'pandas': 'data', 'numpy': 'data', 'scikit-learn': 'ml',
    'pytorch': 'ml', 'tensorflow': 'ml', 'xgboost': 'ml',
    'nlp': 'nlp', 'langchain': 'genai', 'rag': 'genai', 'llm': 'genai',
    'aws': 'cloud', 'gcp': 'cloud', 'azure': 'cloud',
    'docker': 'devops', 'kubernetes': 'devops',
    'power bi': 'bi', 'tableau': 'bi', 'plotly': 'bi',
    'communication': 'soft', 'teamwork': 'soft', 'agile': 'soft',
}

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)       # strip HTML
    text = re.sub(r'[^a-zA-Z0-9#+./\- ]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text

def extract_skills_from_text(text: str) -> list[str]:
    found = []
    for skill in KNOWN_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text):
            found.append(skill)
    return found

def run_etl():
    conn = get_connection()
    df = pd.read_sql('SELECT id, title, description FROM jobs', conn)
    conn.close()

    if df.empty:
        print('[ETL] No jobs found in DB. Run pipeline.py first.')
        return

    print(f'[ETL] Processing {len(df)} jobs...')

    df['clean_desc'] = df['description'].apply(clean_text)

    # TF-IDF on descriptions (for ranking/recommender later)
    vectorizer = TfidfVectorizer(
        max_features=500,
        stop_words='english',
        ngram_range=(1, 2),
    )
    tfidf_matrix = vectorizer.fit_transform(df['clean_desc'])
    feature_names = vectorizer.get_feature_names_out()

    # Save tfidf matrix mapping to DB
    for i, row in df.iterrows():
        job_id = int(row['id'])
        text   = row['clean_desc']
        found_skills = extract_skills_from_text(text)

        # Get TF-IDF scores for skills found in this job
        tfidf_vec = tfidf_matrix[df.index.get_loc(i)]
        tfidf_dense = tfidf_vec.toarray()[0]

        for skill_name in found_skills:
            category = SKILL_CATEGORIES.get(skill_name)
            skill_id = insert_skill(skill_name, category)

            # Find score if skill token is in vocabulary
            score = 0.0
            tokens = skill_name.split()
            for token in tokens:
                if token in feature_names:
                    idx = list(feature_names).index(token)
                    score = max(score, float(tfidf_dense[idx]))

            insert_job_skill(job_id, skill_id, score)

    print(f'[ETL] Done. Skills extracted and saved.')

    # Quick stats
    conn2 = get_connection()
    stats = pd.read_sql('''
        SELECT s.name, COUNT(*) as job_count
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.id
        GROUP BY s.name
        ORDER BY job_count DESC
        LIMIT 15
    ''', conn2)
    conn2.close()
    print('\n[ETL] Top 15 skills in dataset:')
    print(stats.to_string(index=False))

if __name__ == '__main__':
    run_etl()