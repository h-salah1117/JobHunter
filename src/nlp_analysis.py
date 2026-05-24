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
from database import get_connection

# ── cluster labels (tune after seeing your data) ────────────────────────────
CLUSTER_LABELS = {
    0: 'Data Engineering',
    1: 'Machine Learning / AI',
    2: 'Business Intelligence',
    3: 'NLP / GenAI',
    4: 'Software Engineering',
}

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
    df = pd.read_sql(
        'SELECT id, title, description, country, contract_type FROM jobs',
        conn,
    )
    conn.close()
    df['clean'] = df['description'].apply(_clean)
    return df


def generate_wordcloud() -> str:
    """Returns base64 PNG of word cloud from all job descriptions."""
    df = _load_descriptions()
    if df.empty:
        return ''

    text = ' '.join(df['clean'].tolist())

    wc = WordCloud(
        width=900,
        height=450,
        background_color='white',
        colormap='viridis',
        stopwords=MY_STOPWORDS,
        max_words=120,
        collocations=False,
    ).generate(text)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis('off')
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def cluster_jobs(n_clusters: int = 5) -> dict:
    """
    KMeans clustering on job descriptions.
    Returns dict with:
      - labels: list of cluster names per job
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
    df['cluster_label'] = df['cluster_id'].map(
        lambda i: CLUSTER_LABELS.get(i, f'Cluster {i}')
    )

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
        FROM jobs GROUP BY contract_type
    ''', conn)
    conn.close()
    return df.to_dict(orient='records')


def country_salary_heatmap() -> list[dict]:
    conn = get_connection()
    df = pd.read_sql('''
        SELECT country,
               ROUND(AVG(salary_min),0) AS avg_min,
               ROUND(AVG(salary_max),0) AS avg_max,
               COUNT(*) AS job_count
        FROM jobs
        WHERE salary_min IS NOT NULL
        GROUP BY country
        ORDER BY avg_max DESC
    ''', conn)
    conn.close()
    return df.to_dict(orient='records')
