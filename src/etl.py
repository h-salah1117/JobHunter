"""
etl.py — cleans job descriptions and extracts skills using TF-IDF + a curated skill list.

Usage:
    python src/etl.py
"""

import logging
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


def enrich_job_summaries(limit: int = 30):
    """
    Enriches jobs that do not have English or Arabic summaries.
    Queries Groq in JSON mode and saves summaries back to the database.
    """
    import time
    from database import get_connection, update_job_summaries
    from rag_assistant import summarize_description, is_summary_backed_off
    
    if is_summary_backed_off():
        logging.info("[ETL] AI Summarization is currently backed off. Skipping enrichment.")
        return

    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, description
        FROM jobs
        WHERE (summary_en IS NULL OR summary_ar IS NULL OR summary_en = '' OR summary_ar = '')
          AND description IS NOT NULL
          AND description != ''
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        ORDER BY coalesce(posted_at, scraped_at) DESC
        LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        logging.info("[ETL] No jobs need summary enrichment.")
        return
        
    logging.info(f"[ETL] Enriching {len(rows)} jobs with AI summaries...")
    success_count = 0
    for r in rows:
        if is_summary_backed_off():
            logging.info("[ETL] AI Summarization backed off. Stopping loop.")
            break

        job_id = r['id']
        description = r['description']
        try:
            summary_en, summary_ar = summarize_description(description)
            if summary_en and summary_ar:
                update_job_summaries(job_id, summary_en, summary_ar)
                success_count += 1
                time.sleep(0.5)  # Respect rate limits
            else:
                logging.info(f"[ETL] Failed to generate summary for job ID {job_id}")
        except Exception as e:
            logging.info(f"[ETL] Error summarizing job ID {job_id}: {e}")
            if is_summary_backed_off():
                logging.info("[ETL] Daily limit hit during execution. Stopping loop.")
                break
            time.sleep(2)
            
    logging.info(f"[ETL] Enrichment completed: {success_count}/{len(rows)} jobs successfully summarized.")



def run_etl():
    conn = get_connection()
    df = pd.read_sql('SELECT id, title, description FROM jobs', conn)
    conn.close()

    if df.empty:
        logging.info('[ETL] No jobs found in DB. Run pipeline.py first.')
        return

    logging.info(f'[ETL] Processing {len(df)} jobs...')

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
    db_conn = get_connection()
    try:
        for i, row in df.iterrows():
            job_id = int(row['id'])
            text   = row['clean_desc']
            found_skills = extract_skills_from_text(text)

            # Get TF-IDF scores for skills found in this job
            tfidf_vec = tfidf_matrix[df.index.get_loc(i)]
            tfidf_dense = tfidf_vec.toarray()[0]

            for skill_name in found_skills:
                category = SKILL_CATEGORIES.get(skill_name)
                skill_id = insert_skill(skill_name, category, conn=db_conn)

                # Find score if skill token is in vocabulary
                score = 0.0
                tokens = skill_name.split()
                for token in tokens:
                    if token in feature_names:
                        idx = list(feature_names).index(token)
                        score = max(score, float(tfidf_dense[idx]))

                insert_job_skill(job_id, skill_id, score, conn=db_conn)
        db_conn.commit()
    except Exception as e:
        db_conn.rollback()
        logging.error(f"[ETL] Error during skills batch insertion: {e}")
        raise e
    finally:
        db_conn.close()

    logging.info(f'[ETL] Done. Skills extracted and saved.')

    # Extract seniority for all jobs that don't have it yet
    try:
        from salary_model import update_job_seniority
        update_job_seniority()
    except Exception as e:
        logging.info(f'[ETL] seniority extraction error: {e}')

    # Update ChromaDB vector database index
    try:
        from rag_assistant import index_new_jobs
        index_new_jobs()
    except Exception as e:
        logging.info(f'[ETL] ChromaDB indexing error: {e}')

    # Enrich job summaries
    try:
        enrich_job_summaries(limit=30)
    except Exception as e:
        logging.info(f'[ETL] Summarization enrichment error: {e}')

    # Refresh analytics cache
    try:
        from nlp_analysis import refresh_analytics_cache
        refresh_analytics_cache()
    except Exception as e:
        logging.info(f'[ETL] Analytics cache refresh error: {e}')

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
    logging.info('\n[ETL] Top 15 skills in dataset:')
    logging.info(stats.to_string(index=False))

if __name__ == '__main__':
    run_etl()