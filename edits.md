# Codebase Edits Summary — Front-end & UI Polish Session

This document details all the modifications made to the front-end (HTML, CSS, and JS) files during this session to fix bugs, resolve styling issues, and enable interactive ML visualization charts.

---

## 1. Core Stylesheet Updates
* **File**: `app/static/style.css` (view file: [style.css](file:///d:/Data%20scince/JobHunter/app/static/style.css))
* **Reason**: Static stylesheets cannot parse Tailwind `@apply` or CSS Modules `composes` directives when loaded on the client-side via CDN. Dropping them restored styling rendering. Added custom SVG chevrons for dropdown select arrows since `appearance-none` is active.
* **Key Changes**:
  ```css
  /* Body and Selection resets */
  ::selection {
    background-color: rgba(0, 191, 165, 0.3) !important;
    color: #FFD600 !important;
  }
  body {
    background-color: #0D1117;
    color: #F0F6FC;
  }

  /* Nav Links styling */
  .nav-link {
    position: relative;
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 600;
    color: #8B949E;
    transition: all 0.3s ease-out;
  }
  .nav-link.active {
    color: #00BFA5 !important;
    background-color: rgba(0, 191, 165, 0.05);
    border-radius: 0.5rem;
  }

  /* Input and Select Dropdowns with Custom Chevron */
  .form-select {
    background-color: #161B22 !important;
    border: 2px solid #21262D !important;
    color: #F0F6FC !important;
    border-radius: 1rem !important;
    appearance: none !important;
    background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3E%3Cpath stroke='%238B949E' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='m6 8 4 4 4-4'/%3E%3C/svg%3E") !important;
    background-position: right 1rem center !important;
    background-repeat: no-repeat !important;
    background-size: 1.25rem !important;
  }

  /* Analytics layout cards */
  .chart-card {
    background-color: #161B22;
    border: 1px solid rgba(51, 65, 85, 0.3);
    border-radius: 1rem;
    padding: 1.75rem;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .chart-title {
    font-family: 'Poppins', sans-serif;
    font-size: 1rem;
    font-weight: 900;
    color: #F0F6FC;
  }
  ```

---

## 2. Base Template Integration
* **File**: `app/templates/base.html` (view file: [base.html](file:///d:/Data%20scince/JobHunter/app/templates/base.html))
* **Reason**: Missing script block prevented child pages from injecting their charting logic.
* **Key Changes**:
  ```diff
    <script src="{{ url_for('static', filename='main.js') }}"></script>
  + {% block scripts %}{% endblock %}
  </body>
  </html>
  ```

---

## 3. Interactive Plotly Charts Rendering
* **File**: `app/templates/analytics.html` (view file: [analytics.html](file:///d:/Data%20scince/JobHunter/app/templates/analytics.html))
* **Reason**: No javascript block existed to render the charts in Flask.
* **Key Changes**: Added `{% block scripts %}` block containing Plotly configurations matching the dark/teal/gold dashboard aesthetics:
  - **Skill Demand Ranking (trends)**: Horizontal bar chart grouping the top 25 skills.
  - **Job Clusters (KMeans ML)**: Interactive 2D scatter plot color-coded by KMeans category.
  - **Skill Co-occurrence Heatmap**: Density matrix showing skills matching.
  - **Average Base Salary Metrics by Country**: Grouped bar chart comparing avg min and max salary pack ranges.

---

## 4. Javascript Functionality & Event Listeners
* **File**: `app/static/main.js` (view file: [main.js](file:///d:/Data%20scince/JobHunter/app/static/main.js))
* **Reason**: Prevent global form selectors from auto-submitting POST forms (like skills matching), and trigger a reload after sync completes.
* **Key Changes**:
  ```diff
  -// Auto-submit filter forms on select change
  -document.querySelectorAll('form select').forEach(sel => {
  +document.querySelectorAll('form.auto-submit select').forEach(sel => {
     sel.addEventListener('change', () => sel.closest('form').submit());
   });

  // Manual refresh reload
   function triggerRefresh(btn) {
     ...
     fetch('/api/refresh', { method: 'POST' })
       .then(r => r.json())
       .then(() => {
         btn.textContent = 'Done ✓';
         showToast('Market metrics synchronized successfully!', 'success');
         setTimeout(() => {
  -        btn.textContent = nativeText;
  -        btn.disabled = false;
  -      }, 3000);
  +        window.location.reload();
  +      }, 1000);
       })
   }
  ```

---

## 5. Job Filters Form
* **File**: `app/templates/jobs.html` (view file: [jobs.html](file:///d:/Data%20scince/JobHunter/app/templates/jobs.html))
* **Reason**: Enable the filter dropdown change listener on the job search form by tagging it with `auto-submit`.
* **Key Changes**:
  ```diff
  -<form method="GET" action="/jobs" class="bg-[#161B22] border border-slate-800/80 p-5 rounded-2xl flex flex-wrap items-center gap-4 mb-10 shadow-xl">
  +<form method="GET" action="/jobs" class="auto-submit bg-[#161B22] border border-slate-800/80 p-5 rounded-2xl flex flex-wrap items-center gap-4 mb-10 shadow-xl">
  ```

---

## 6. Performance & Page Latency Analysis (Future Recommendations)

During page loading verification, we identified a delay (up to 3–5 seconds) when navigating between pages (especially `/analytics`). Below is the root-cause analysis and proposed optimizations.

### Root Cause
1. **Synchronous ML Pipelines (Main Bottleneck)**:
   - On every request to `/analytics`, the backend runs **TF-IDF Vectorization**, fits **KMeans Clustering** and **PCA** models on 1,822+ records, and plots a **Word Cloud** via Matplotlib on the main thread.
2. **In-Memory Filtering**:
   - The `/jobs` and `/` routes load up to 5,000 database records into memory to extract unique filter criteria (like countries and job types) using Python operations on every render, instead of utilizing SQL aggregations.

### Recommendations
1. **ML Cache Layer**:
   - Calculate KMeans, PCA coordinates, and the Word Cloud image **only once** when the background scheduler updates the database (every 6 hours) or when the user clicks "REFRESH".
   - Store the computed JSON array and base64 image in a cached configuration table or a local `cache.json` file, and load it instantly (<50ms) on request.
2. **SQL Query Refactoring**:
   - Re-write filter queries to leverage database indexing and SQL distinct fetches (e.g., `SELECT DISTINCT country FROM jobs`).

---

## 7. Week 3 — Salary Prediction & Seniority Integration
* **Files**: 
  - `src/recommender.py` ([recommender.py](file:///d:/Data%20scince/JobHunter/src/recommender.py))
  - `src/salary_model.py` ([salary_model.py](file:///d:/Data%20scince/JobHunter/src/salary_model.py))
  - `app/routes.py` ([routes.py](file:///d:/Data%20scince/JobHunter/app/routes.py))
  - `app/templates/jobs.html` ([jobs.html](file:///d:/Data%20scince/JobHunter/app/templates/jobs.html))
  - `app/templates/recommend.html` ([recommend.html](file:///d:/Data%20scince/JobHunter/app/templates/recommend.html))
* **Reason**: Full stack integration of the GradientBoostingRegressor model and seniority level extraction.
* **Key Changes**:
  - **Recommender Query & Filtering**: Updated `recommend()` in `recommender.py` to retrieve `seniority`, `contract_type`, and `description` from the database. Handled filters directly during the candidate search phase instead of post-processing.
  - **ML Predictor Cache & Types**: Added an in-memory cached model loader `_load_salary_models()` in `salary_model.py` to eliminate slow disk I/O when predicting in a loop. Fixed the encoding exception path to return integer `0` fallback values rather than class names as strings to prevent numpy casting crashes.
  - **Jinja2 NaN Normalization**: Resolved a truthy evaluation bug where pandas `float('nan')` was treated as a valid value inside Jinja templates. Added check `x != x` in Flask routes to normalize `NaN` values to standard python `None` objects before template rendering.
  - **UI Indicators**: Added ML predicted indicators (`🤖 £min–£max (ML)`) on both the live jobs feed and recommendation result cards.
