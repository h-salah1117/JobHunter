---
title: JobHunter
emoji: 🎯
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: AI-powered job aggregator, recommender & career coach
---

# JobHunter 🎯

An AI-powered job hunting platform that scrapes, recommends, and helps you land your next data science role.

## Features
- 🔍 Live job listings from Adzuna, Wuzzuf & JobSpy
- 🤖 AI job recommender (KNN + TF-IDF skill matching)
- 📄 CV upload & ATS scoring with LLM feedback
- 💬 RAG-powered career coach chatbot (Qwen 2.5)
- 📊 Analytics dashboard with 7 Plotly charts
- 🌐 Bilingual English / Arabic interface

## Setup (HF Spaces Secrets)
Set these in your Space Settings → Variables and Secrets:
- `ADZUNA_APP_ID` — Adzuna API ID
- `ADZUNA_APP_KEY` — Adzuna API Key
- `HF_TOKEN` — HuggingFace token (for serverless LLM)
- `SECRET_KEY` — Random secret string for Flask sessions
- `SCRAPER_MODE` — Set to `production`
