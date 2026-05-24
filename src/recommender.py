"""
recommender.py — KNN-based job recommender using TF-IDF skill vectors.

Given a list of user skills, returns the top-N most similar jobs.
Also supports country/job_type filtering (for the future toggle feature).
"""

import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import MultiLabelBinarizer
from database import get_connection

def load_job_skill_matrix() -> tuple[pd.DataFrame, list[str], list[str]]:
    """Returns (matrix_df, job_ids, skill_names)."""
    conn = get_connection()
    df = pd.read_sql('''
        SELECT js.job_id, s.name AS skill, js.tfidf_score
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.id
    ''', conn)
    conn.close()

    if df.empty:
        return pd.DataFrame(), [], []

    pivot = df.pivot_table(
        index='job_id',
        columns='skill',
        values='tfidf_score',
        fill_value=0.0,
    )
    return pivot, list(pivot.index.astype(str)), list(pivot.columns)

def recommend(
    user_skills: list[str],
    top_n: int = 5,
    country_filter: str | None = None,   # None = all countries
    job_type_filter: str | None = None,  # None = all types (remote/onsite/hybrid)
    contract_type_filter: str | None = None,
    seniority_filter: str | None = None,
) -> pd.DataFrame:
    """
    Recommend top_n jobs matching user_skills with filters.
    """
    pivot, job_ids, skill_names = load_job_skill_matrix()
    if pivot.empty:
        return pd.DataFrame(columns=['title', 'company', 'location', 'job_type', 'match_score', 'source_url'])

    # Build user vector
    user_vec = np.zeros(len(skill_names))
    for i, skill in enumerate(skill_names):
        if skill.lower() in [s.lower() for s in user_skills]:
            user_vec[i] = 1.0

    if user_vec.sum() == 0:
        return pd.DataFrame(columns=['title', 'company', 'location', 'job_type', 'match_score', 'source_url'])

    # Fit KNN (grab more neighbors to allow filtering)
    knn = NearestNeighbors(n_neighbors=min(top_n * 20, len(pivot)), metric='cosine')
    knn.fit(pivot.values)

    distances, indices = knn.kneighbors([user_vec])
    matched_job_ids = [int(pivot.index[i]) for i in indices[0]]
    scores = [round(1 - d, 3) for d in distances[0]]

    # Fetch job details
    conn = get_connection()
    placeholders = ','.join('?' * len(matched_job_ids))
    query = f'''
        SELECT j.id, j.title, co.name AS company, j.location,
               j.country, j.job_type, j.contract_type, j.seniority,
               j.salary_min, j.salary_max, j.source_url, j.description
        FROM jobs j
        LEFT JOIN companies co ON j.company_id = co.id
        WHERE j.id IN ({placeholders})
    '''
    df = pd.read_sql(query, conn, params=matched_job_ids)
    conn.close()

    # Attach scores
    score_map = {job_id: score for job_id, score in zip(matched_job_ids, scores)}
    df['match_score'] = df['id'].map(score_map)
    df = df.sort_values('match_score', ascending=False)

    # Apply filters
    if country_filter and country_filter != 'all':
        df = df[df['country'].str.lower() == country_filter.lower()]
    if job_type_filter and job_type_filter != 'all':
        df = df[df['job_type'] == job_type_filter]
    if contract_type_filter and contract_type_filter != 'all':
        df = df[df['contract_type'] == contract_type_filter]
    if seniority_filter and seniority_filter != 'all':
        df = df[df['seniority'] == seniority_filter]

    res_df = df.head(top_n).reset_index(drop=True)
    return res_df.where(pd.notnull(res_df), None)

def get_top_skills(limit: int = 20) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(f'''
        SELECT s.name, s.category, COUNT(*) AS job_count
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.id
        GROUP BY s.name
        ORDER BY job_count DESC
        LIMIT {limit}
    ''', conn)
    conn.close()
    return df

def get_salary_stats() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql('''
        SELECT
            country,
            job_type,
            ROUND(AVG(salary_min), 0) AS avg_min,
            ROUND(AVG(salary_max), 0) AS avg_max,
            COUNT(*) AS job_count
        FROM jobs
        WHERE salary_min IS NOT NULL
        GROUP BY country, job_type
        ORDER BY avg_max DESC
    ''', conn)
    conn.close()
    return df