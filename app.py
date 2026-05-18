
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import streamlit as st
import pandas as pd
import plotly.express as px
from database import fetch_all_jobs
from recommender import recommend, get_top_skills, get_salary_stats

st.set_page_config(
    page_title='Job Market AI',
    page_icon='🔍',
    layout='wide',
)

# ── Styles ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        border: 1px solid #e9ecef;
    }
    .match-badge {
        background: #e8f5e9;
        color: #2e7d32;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 600;
    }
    .remote-badge { background:#e3f2fd; color:#1565c0; padding:3px 8px; border-radius:12px; font-size:12px; }
    .hybrid-badge { background:#fff3e0; color:#e65100; padding:3px 8px; border-radius:12px; font-size:12px; }
    .onsite-badge { background:#f3e5f5; color:#6a1b9a; padding:3px 8px; border-radius:12px; font-size:12px; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title('⚙️ Filters')

    st.markdown('---')
    st.subheader('Job recommender')
    skills_input = st.text_input(
        'Your skills (comma-separated)',
        placeholder='python, sql, pandas, nlp',
    )
    top_n = st.slider('Results to show', 3, 20, 5)

    st.markdown('---')

    # ── COUNTRY FILTER TOGGLE (wired in, ready to use) ───────────────────
    st.subheader('Location preference')
    location_mode = st.radio(
        'Show jobs from:',
        ['All countries', 'Specific country', 'Remote only'],
        index=0,
    )

    selected_country = None
    job_type_filter  = None

    if location_mode == 'Remote only':
        job_type_filter = 'remote'
        st.info('Showing remote jobs only 🌍')

    elif location_mode == 'Specific country':
        jobs_df = pd.DataFrame(fetch_all_jobs())
        if not jobs_df.empty and 'country' in jobs_df.columns:
            countries = sorted(jobs_df['country'].dropna().unique().tolist())
            selected_country = st.selectbox('Select country', countries)
        else:
            st.warning('No jobs loaded yet.')

    st.markdown('---')
    st.caption('Job Market AI — MVP v0.1')

# ── Main ─────────────────────────────────────────────────────────────────────
st.title('🔍 Job Market Intelligence')

tab_dash, tab_rec, tab_jobs = st.tabs(['📊 Dashboard', '🎯 Recommend', '📋 All Jobs'])

# ── TAB 1: Dashboard ────────────────────────────────────────────────────────
with tab_dash:
    all_jobs = fetch_all_jobs()
    if not all_jobs:
        st.warning('No data yet. Run `python src/pipeline.py` then `python src/etl.py` first.')
        st.stop()

    df = pd.DataFrame(all_jobs)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Total jobs', f"{len(df):,}")
    col2.metric('Companies', f"{df['company_name'].nunique():,}")
    col3.metric('Remote jobs', f"{(df['job_type'] == 'remote').sum():,}")
    col4.metric('Countries', f"{df['country'].nunique():,}")

    st.markdown('---')
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader('Top skills in demand')
        top_skills = get_top_skills(20)
        if not top_skills.empty:
            fig = px.bar(
                top_skills,
                x='job_count',
                y='name',
                orientation='h',
                color='category',
                title='',
                height=450,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                showlegend=True,
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader('Job type distribution')
        type_counts = df['job_type'].value_counts().reset_index()
        type_counts.columns = ['type', 'count']
        fig2 = px.pie(
            type_counts, values='count', names='type',
            color_discrete_sequence=['#7986CB', '#4DB6AC', '#FFB74D'],
            height=220,
        )
        fig2.update_traces(textposition='inside', textinfo='percent+label')
        fig2.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader('Jobs by country')
        country_counts = df['country'].value_counts().head(10).reset_index()
        country_counts.columns = ['country', 'count']
        fig3 = px.bar(
            country_counts, x='country', y='count',
            color_discrete_sequence=['#5C6BC0'],
            height=220,
        )
        fig3.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig3, use_container_width=True)

    salary_df = get_salary_stats()
    if not salary_df.empty:
        st.subheader('Salary overview')
        st.dataframe(salary_df, use_container_width=True, hide_index=True)

# ── TAB 2: Recommender ───────────────────────────────────────────────────────
with tab_rec:
    st.subheader('Find jobs matching your skills')

    if not skills_input.strip():
        st.info('Enter your skills in the sidebar to get recommendations.')
    else:
        user_skills = [s.strip().lower() for s in skills_input.split(',') if s.strip()]
        st.write(f"Matching against: {', '.join(f'`{s}`' for s in user_skills)}")

        with st.spinner('Finding best matches...'):
            results = recommend(
                user_skills,
                top_n=top_n,
                country_filter=selected_country,
                job_type_filter=job_type_filter,
            )

        if results.empty:
            st.warning('No matches found. Try different skills or remove location filters.')
        else:
            st.success(f'Found {len(results)} matching jobs')
            for _, row in results.iterrows():
                with st.container():
                    col_title, col_score = st.columns([4, 1])
                    with col_title:
                        st.markdown(f"#### {row['title']}")
                        badge_class = f"{row.get('job_type', 'onsite')}-badge"
                        st.markdown(
                            f"🏢 **{row['company']}** &nbsp; 📍 {row['location']} &nbsp; "
                            f"<span class='{badge_class}'>{row.get('job_type', 'onsite')}</span>",
                            unsafe_allow_html=True,
                        )
                    with col_score:
                        score_pct = int(row['match_score'] * 100)
                        st.markdown(
                            f"<div style='text-align:center'>"
                            f"<span class='match-badge'>{score_pct}% match</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    if row.get('source_url'):
                        st.markdown(f"[View job →]({row['source_url']})")
                    st.divider()

# ── TAB 3: All Jobs ───────────────────────────────────────────────────────────
with tab_jobs:
    st.subheader('All jobs in database')
    all_df = pd.DataFrame(fetch_all_jobs())
    if all_df.empty:
        st.info('No jobs yet.')
    else:
        search = st.text_input('Search by title or company', '')
        if search:
            mask = (
                all_df['title'].str.contains(search, case=False, na=False) |
                all_df['company_name'].str.contains(search, case=False, na=False)
            )
            all_df = all_df[mask]

        display_cols = ['title', 'company_name', 'location', 'country', 'job_type', 'salary_min', 'salary_max']
        st.dataframe(
            all_df[display_cols].rename(columns={'company_name': 'company'}),
            use_container_width=True,
            hide_index=True,
        )