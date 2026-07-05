"""
nlp_analysis.py — NLP analytics: word cloud, KMeans job clustering, skill trends.
Returns chart-ready JSON for Flask/Plotly.js or saves PNG for embedding.
"""

import re
import io
import base64
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from wordcloud import WordCloud, STOPWORDS as WC_STOPWORDS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import get_connection, get_seniority_breakdown, get_avg_salary_by_seniority


# Cluster labels are dynamically generated using top TF-IDF terms per clustercentroid.

MY_STOPWORDS = set(WC_STOPWORDS).union({
    'the', 'and', 'for', 'with', 'you', 'will', 'our', 'are', 'this',
    'have', 'that', 'from', 'your', 'work', 'team', 'role', 'looking',
    'experience', 'skills', 'working', 'ability', 'strong', 'good',
    'new', 'join', 'able', 'part', 'also', 'help', 'well', 'use',
    'using', 'used', 'knowledge', 'understanding', 'excellent',
})


def _clean(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text or '')
    text = re.sub(r'[^a-zA-Z0-9+# ]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip().lower()


def _load_descriptions() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql('''
        SELECT id, title, description, country, contract_type 
        FROM jobs
        WHERE datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
    ''', conn)
    conn.close()
    df['clean'] = df['description'].apply(_clean)
    return df


def generate_wordcloud() -> str:
    """Returns base64 PNG of word cloud with transparent background and cyberpunk colormap."""
    df = _load_descriptions()
    if df.empty:
        return ''

    text = ' '.join(df['clean'].tolist())

    wc = WordCloud(
        width=900,
        height=450,
        background_color=None,
        mode='RGBA',
        colormap='cool',
        stopwords=MY_STOPWORDS,
        max_words=120,
        collocations=False,
    ).generate(text)

    fig, ax = plt.subplots(figsize=(10, 5), facecolor='none')
    ax.imshow(wc, interpolation='bilinear')
    ax.axis('off')
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def cluster_jobs(n_clusters: int = 5) -> dict:
    """
    KMeans clustering on job descriptions with dynamic TF-IDF centroid labels.
    Returns dict with:
      - scatter: x, y, title, cluster (for Plotly scatter)
      - counts: cluster name → count
    """
    df = _load_descriptions()
    if len(df) < n_clusters:
        return {}

    vec = TfidfVectorizer(max_features=300, stop_words='english', ngram_range=(1, 2))
    X = vec.fit_transform(df['clean'])

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['cluster_id'] = km.fit_predict(X)
    
    # Extract top 3 features per cluster dynamically
    feature_names = vec.get_feature_names_out()
    centroids = km.cluster_centers_
    cluster_labels = {}
    for i in range(n_clusters):
        top_indices = centroids[i].argsort()[::-1][:3]
        top_terms = [feature_names[idx] for idx in top_indices]
        cluster_labels[i] = f"Cluster {i}: " + ", ".join(top_terms)

    df['cluster_label'] = df['cluster_id'].map(cluster_labels)

    # PCA → 2D for scatter plot
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X.toarray())
    df['x'] = coords[:, 0]
    df['y'] = coords[:, 1]

    scatter = df[['x', 'y', 'title', 'cluster_label']].rename(
        columns={'cluster_label': 'cluster'}
    ).to_dict(orient='records')

    counts = df['cluster_label'].value_counts().to_dict()

    return {'scatter': scatter, 'counts': counts}


def skill_trends() -> list[dict]:
    """Top skills with count + category, sorted by demand."""
    conn = get_connection()
    df = pd.read_sql('''
        SELECT s.name, s.category, COUNT(*) AS job_count
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.id
        JOIN jobs j ON js.job_id = j.id
        WHERE datetime(coalesce(j.posted_at, j.scraped_at)) >= datetime('now', '-30 days')
        GROUP BY s.name
        ORDER BY job_count DESC
        LIMIT 25
    ''', conn)
    conn.close()
    return df.to_dict(orient='records')


def skill_cooccurrence(top_n: int = 15) -> dict:
    """
    Which skills appear together most?
    Returns adjacency dict suitable for a heatmap.
    """
    conn = get_connection()
    df = pd.read_sql('''
        SELECT js.job_id, s.name
        FROM job_skills js
        JOIN skills s ON js.skill_id = s.id
        JOIN jobs j ON js.job_id = j.id
        WHERE datetime(coalesce(j.posted_at, j.scraped_at)) >= datetime('now', '-30 days')
    ''', conn)
    conn.close()

    if df.empty:
        return {}

    top_skills = (
        df['name'].value_counts().head(top_n).index.tolist()
    )
    df = df[df['name'].isin(top_skills)]

    pivot = df.pivot_table(
        index='job_id', columns='name', aggfunc=lambda x: 1, fill_value=0
    )
    cooc = pivot.T.dot(pivot)
    np.fill_diagonal(cooc.values, 0)

    return {
        'skills': cooc.columns.tolist(),
        'matrix': cooc.values.tolist(),
    }


def contract_type_breakdown() -> list[dict]:
    conn = get_connection()
    df = pd.read_sql('''
        SELECT contract_type, COUNT(*) as count
        FROM jobs 
        WHERE datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
        GROUP BY contract_type
    ''', conn)
    conn.close()
    return df.to_dict(orient='records')


def country_salary_heatmap() -> list[dict]:
    """Average base salary metrics by country, normalized to USD ($) for comparison."""
    conn = get_connection()
    df = pd.read_sql('''
        SELECT country, salary_min, salary_max
        FROM jobs
        WHERE salary_min IS NOT NULL
          AND datetime(coalesce(posted_at, scraped_at)) >= datetime('now', '-30 days')
    ''', conn)
    conn.close()

    if df.empty:
        return []

    # Convert UK salaries from GBP to USD (1 GBP ~ 1.25 USD)
    gbp_mask = df['country'].str.lower().isin(['united kingdom', 'gb', 'uk'])
    df.loc[gbp_mask, 'salary_min'] = df.loc[gbp_mask, 'salary_min'] * 1.25
    df.loc[gbp_mask, 'salary_max'] = df.loc[gbp_mask, 'salary_max'] * 1.25

    grouped = df.groupby('country').agg(
        avg_min=('salary_min', 'mean'),
        avg_max=('salary_max', 'mean'),
        job_count=('salary_min', 'count')
    ).reset_index()

    grouped['avg_min'] = grouped['avg_min'].round(0)
    grouped['avg_max'] = grouped['avg_max'].round(0)
    grouped = grouped.sort_values(by='avg_max', ascending=False)

    return grouped.to_dict(orient='records')


CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'analytics_cache.json')

def refresh_analytics_cache() -> dict:
    """Generates all analytics data and saves it to a local JSON cache file."""
    import logging
    logging.info("[NLP] Refreshing analytics cache...")
    try:
        data = {
            'wordcloud_b64': generate_wordcloud(),
            'clusters': cluster_jobs(n_clusters=5),
            'trends': skill_trends(),
            'cooc': skill_cooccurrence(top_n=12),
            'salary_data': country_salary_heatmap(),
            'seniority_breakdown': get_seniority_breakdown(),
            'salary_by_seniority': get_avg_salary_by_seniority(),
        }
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        import json
        with open(CACHE_PATH, 'w') as f:
            json.dump(data, f)
        logging.info("[NLP] Analytics cache refreshed successfully.")
        return data
    except Exception as e:
        logging.error(f"[NLP] Error refreshing analytics cache: {e}")
        return {}

def get_analytics_data(force_refresh: bool = False) -> dict:
    """Retrieves analytics data from the cache file, or computes it on the fly if missing."""
    import json
    import logging
    if not force_refresh and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"[NLP] Error reading analytics cache file: {e}")

    # Fallback to computing on demand and updating cache
    return refresh_analytics_cache()

