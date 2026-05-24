"""
salary_model.py — Salary prediction & seniority extraction.

Week 3 deliverables:
1. GradientBoostingRegressor for salary range prediction
2. Seniority extraction from job descriptions (junior/mid/senior/lead)
3. Store seniority in jobs table for filtering
4. REST API endpoint: /api/salary-predict

Usage:
    python src/salary_model.py --train    # Train and save model
    # Then use in Flask routes or directly
"""

import os
import re
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

import sys
sys.path.insert(0, os.path.dirname(__file__))
from database import get_connection

# ── Model paths ────────────────────────────────────────────────────────────
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

MODEL_MIN_PATH = os.path.join(MODEL_DIR, 'salary_min_model.pkl')
MODEL_MAX_PATH = os.path.join(MODEL_DIR, 'salary_max_model.pkl')
ENCODER_PATH   = os.path.join(MODEL_DIR, 'job_type_encoder.pkl')
COUNTRY_ENC_PATH = os.path.join(MODEL_DIR, 'country_encoder.pkl')

# ── Seniority patterns ──────────────────────────────────────────────────────
SENIORITY_PATTERNS = {
    'lead': r'\b(?:lead|head of|principal|director|manager|executive|chief)\b',
    'senior': r'\b(?:senior|sr\.?|lead|staff|architect|principal)\b',
    'mid': r'\b(?:mid(?:[-\s]level)?|intermediate|experienced|3\+|4\+|5\+)\b',
    'junior': r'\b(?:junior|jr\.?|entry(?:\s)?level|graduate|fresh|intern|0\-2|0-1)\b',
}

# ── Feature engineering ────────────────────────────────────────────────────
def extract_seniority(title: str, desc: str) -> str:
    """Extract seniority level from job title + description."""
    text = (title + ' ' + desc).lower()

    # Check in order of specificity
    for level in ['lead', 'senior', 'mid', 'junior']:
        if re.search(SENIORITY_PATTERNS[level], text):
            return level

    return 'mid'  # default

def extract_has_remote(job_type: str) -> int:
    """1 if remote/hybrid, 0 if onsite."""
    return 1 if job_type in ['remote', 'hybrid'] else 0

def extract_is_internship(contract_type: str) -> int:
    """1 if internship, 0 otherwise."""
    return 1 if contract_type == 'internship' else 0

def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Prepare features for model training/prediction."""
    df = df.copy()

    # Extract seniority
    df['seniority'] = df.apply(
        lambda row: extract_seniority(
            str(row.get('title', '')),
            str(row.get('description', ''))
        ),
        axis=1
    )

    # Binary features
    df['has_remote'] = df['job_type'].apply(extract_has_remote)
    df['is_internship'] = df['contract_type'].apply(extract_is_internship)

    # Group countries (encode top countries, others → 'other')
    top_countries = ['United Kingdom', 'United States', 'Egypt', 'United Arab Emirates', 'Saudi Arabia']
    df['country_group'] = df['country'].apply(
        lambda c: c if c in top_countries else 'other'
    )

    return df, ['seniority', 'has_remote', 'is_internship', 'country_group']

def train_salary_models():
    """Train salary min/max models. Call once at startup or on demand."""
    print('[SalaryModel] Loading training data...')

    conn = get_connection()
    df = pd.read_sql('''
        SELECT title, description, country, job_type, contract_type,
               salary_min, salary_max
        FROM jobs
        WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL
          AND salary_min > 0 AND salary_max > 0
          AND salary_min < 500000 AND salary_max < 500000
    ''', conn)
    conn.close()

    if df.empty:
        print('[SalaryModel] No salary data to train on yet.')
        return

    print(f'[SalaryModel] Training on {len(df)} jobs with salary data...')

    df, feature_cols = prepare_features(df)

    # Encode categorical features
    le_seniority = LabelEncoder()
    le_country = LabelEncoder()
    df['seniority_enc'] = le_seniority.fit_transform(df['seniority'])
    df['country_enc'] = le_country.fit_transform(df['country_group'])

    X = df[['seniority_enc', 'has_remote', 'is_internship', 'country_enc']].values
    y_min = df['salary_min'].values
    y_max = df['salary_max'].values

    # Train/test split
    X_train, X_test, y_min_train, y_min_test, y_max_train, y_max_test = train_test_split(
        X, y_min, y_max, test_size=.2, random_state=42
    )

    # Train min salary model
    print('[SalaryModel] Training salary_min regressor...')
    gbr_min = GradientBoostingRegressor(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        random_state=42,
    )
    gbr_min.fit(X_train, y_min_train)
    y_min_pred = gbr_min.predict(X_test)
    mae_min = mean_absolute_error(y_min_test, y_min_pred)
    r2_min = r2_score(y_min_test, y_min_pred)
    print(f'  MAE: £{mae_min:.2f} | R²: {r2_min:.3f}')

    # Train max salary model
    print('[SalaryModel] Training salary_max regressor...')
    gbr_max = GradientBoostingRegressor(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        random_state=42,
    )
    gbr_max.fit(X_train, y_max_train)
    y_max_pred = gbr_max.predict(X_test)
    mae_max = mean_absolute_error(y_max_test, y_max_pred)
    r2_max = r2_score(y_max_test, y_max_pred)
    print(f'  MAE: £{mae_max:.2f} | R²: {r2_max:.3f}')

    # Save models + encoders
    with open(MODEL_MIN_PATH, 'wb') as f:
        pickle.dump(gbr_min, f)
    with open(MODEL_MAX_PATH, 'wb') as f:
        pickle.dump(gbr_max, f)
    with open(ENCODER_PATH, 'wb') as f:
        pickle.dump({'seniority': le_seniority, 'country': le_country}, f)

    print(f'[SalaryModel] Models saved to {MODEL_DIR}')
    return {'mae_min': mae_min, 'mae_max': mae_max, 'r2_min': r2_min, 'r2_max': r2_max}

_MODEL_CACHE = None

def _load_salary_models():
    """Load models from disk or return cached versions."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    if not os.path.exists(MODEL_MIN_PATH) or not os.path.exists(MODEL_MAX_PATH):
        print('[SalaryModel] Models not found. Training first...')
        train_salary_models()

    if not os.path.exists(MODEL_MIN_PATH):
        return None

    try:
        with open(MODEL_MIN_PATH, 'rb') as f:
            gbr_min = pickle.load(f)
        with open(MODEL_MAX_PATH, 'rb') as f:
            gbr_max = pickle.load(f)
        with open(ENCODER_PATH, 'rb') as f:
            encoders = pickle.load(f)
        
        _MODEL_CACHE = (gbr_min, gbr_max, encoders)
        return _MODEL_CACHE
    except Exception as e:
        print(f'[SalaryModel] Error loading models: {e}')
        return None

def predict_salary(title: str, description: str, country: str, job_type: str, contract_type: str) -> dict:
    """Predict salary range for a job."""
    cache = _load_salary_models()
    if cache is None:
        return {'error': 'Models not available', 'salary_min': None, 'salary_max': None}

    gbr_min, gbr_max, encoders = cache
    le_seniority = encoders['seniority']
    le_country = encoders['country']

    # Prepare features
    seniority = extract_seniority(title, description)
    has_remote = extract_has_remote(job_type)
    is_internship = extract_is_internship(contract_type)
    country_group = country if country in ['United Kingdom', 'United States', 'Egypt', 'United Arab Emirates', 'Saudi Arabia'] else 'other'

    # Encode
    try:
        seniority_enc = int(le_seniority.transform([seniority])[0])
    except (ValueError, KeyError, IndexError):
        seniority_enc = 0

    try:
        country_enc = int(le_country.transform([country_group])[0])
    except (ValueError, KeyError, IndexError):
        country_enc = 0

    X = np.array([[seniority_enc, has_remote, is_internship, country_enc]])

    # Predict
    pred_min = float(gbr_min.predict(X)[0])
    pred_max = float(gbr_max.predict(X)[0])

    # Ensure min < max
    if pred_min > pred_max:
        pred_min, pred_max = pred_max, pred_min

    return {
        'salary_min': max(0, round(pred_min, 0)),
        'salary_max': max(0, round(pred_max, 0)),
        'seniority': seniority,
        'currency': 'GBP' if country == 'United Kingdom' else 'USD' if country == 'United States' else 'EGP' if country == 'Egypt' else 'AED',
    }

def update_job_seniority():
    """Update jobs table with extracted seniority levels."""
    print('[SalaryModel] Updating job seniority...')

    conn = get_connection()
    df = pd.read_sql('SELECT id, title, description FROM jobs WHERE seniority IS NULL', conn)
    conn.close()

    if df.empty:
        print('[SalaryModel] No jobs to update.')
        return

    updated = 0
    for _, row in df.iterrows():
        seniority = extract_seniority(str(row['title']), str(row['description']))
        conn = get_connection()
        conn.execute('UPDATE jobs SET seniority = ? WHERE id = ?', (seniority, row['id']))
        conn.commit()
        conn.close()
        updated += 1

    print(f'[SalaryModel] Updated {updated} jobs with seniority.')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', action='store_true', help='Train and save models')
    parser.add_argument('--update-seniority', action='store_true', help='Extract seniority for all jobs')
    args = parser.parse_args()

    if args.train:
        train_salary_models()
    if args.update_seniority:
        update_job_seniority()
    if not args.train and not args.update_seniority:
        print('Usage: python salary_model.py [--train] [--update-seniority]')
