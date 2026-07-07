"""
rag_assistant.py — RAG Career Assistant core logic.
Uses ChromaDB for vector storage, SentenceTransformers (multilingual-e5-base) for embeddings,
and Hugging Face (InferenceClient / local model) for LLM generation.
"""

import logging
import os
import sqlite3
import numpy as np
import pandas as pd
import chromadb
from dotenv import load_dotenv
load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.db')
CHROMA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')

# ── Caches ───────────────────────────────────────────────────────────────────
_embedding_model = None
_hf_pipelines = {}
_hf_inference_clients = {}
_chroma_client = None
_chroma_collection = None

def set_summary_backoff(until_datetime):
    pass

def get_summary_backoff():
    return None

def is_summary_backed_off() -> bool:
    return False

def _get_embedding_model():
    """Cache SentenceTransformer model in memory."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logging.info("[RAG] Loading SentenceTransformer (intfloat/multilingual-e5-base)...")
        _embedding_model = SentenceTransformer('intfloat/multilingual-e5-base')
    return _embedding_model

def _get_hf_client_or_pipeline(model_type='chat', force_local=False):
    """
    Returns (client, pipeline) depending on configuration and model type.
    Prioritizes InferenceClient (Serverless API) if HF_TOKEN or HF_API_TOKEN is in environment.
    Falls back to loading local model.
    """
    global _hf_pipelines, _hf_inference_clients
    
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")
    
    # Custom model selection by type
    if model_type == 'chat':
        api_model = os.getenv("HF_API_MODEL_CHAT") or os.getenv("HF_API_MODEL") or "Qwen/Qwen2.5-72B-Instruct"
        local_model = os.getenv("HF_LOCAL_MODEL_CHAT") or os.getenv("HF_LOCAL_MODEL") or "Qwen/Qwen2.5-0.5B-Instruct"
    else: # summary
        api_model = os.getenv("HF_API_MODEL_SUMMARY") or os.getenv("HF_API_MODEL") or "meta-llama/Llama-3.2-3B-Instruct"
        local_model = os.getenv("HF_LOCAL_MODEL_SUMMARY") or os.getenv("HF_LOCAL_MODEL") or "Qwen/Qwen2.5-0.5B-Instruct"
        
    if hf_token and not force_local:
        if api_model not in _hf_inference_clients:
            from huggingface_hub import InferenceClient
            logging.info(f"[RAG] Initializing HF InferenceClient ({model_type}) with model: {api_model}...")
            _hf_inference_clients[api_model] = InferenceClient(model=api_model, token=hf_token)
        return _hf_inference_clients[api_model], None
        
    # Local fallback
    if local_model not in _hf_pipelines:
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        import torch
        logging.info(f"[RAG] Initializing local model ({model_type}): {local_model}...")
        
        tokenizer = AutoTokenizer.from_pretrained(local_model)
        model = AutoModelForCausalLM.from_pretrained(
            local_model,
            torch_dtype=torch.float32 if not torch.cuda.is_available() else torch.float16
        )
        if torch.cuda.is_available():
            model = model.to("cuda")
        _hf_pipelines[local_model] = pipeline("text-generation", model=model, tokenizer=tokenizer)
        logging.info(f"[RAG] Local model ({model_type}) loaded successfully!")
        
    return None, _hf_pipelines[local_model]

def _call_llm_hf(messages, temperature=0.7, max_tokens=600, json_mode=False, model_type='chat') -> str:
    """Wrapper that routes prompt to serverless InferenceClient or local transformers pipeline."""
    client, pipe = _get_hf_client_or_pipeline(model_type=model_type)
    
    if client:
        try:
            chat_history = [{"role": m["role"], "content": m["content"]} for m in messages]
            response = client.chat_completion(
                messages=chat_history,
                temperature=temperature if not json_mode else 0.1,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"[RAG] HF InferenceClient API call failed: {e}. Falling back to local pipeline...")
            _, pipe = _get_hf_client_or_pipeline(model_type=model_type, force_local=True)
            
    if pipe:
        try:
            prompt_formatted = pipe.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            outputs = pipe(
                prompt_formatted,
                max_new_tokens=max_tokens,
                do_sample=True if not json_mode else False,
                temperature=temperature if not json_mode else 0.1,
                top_p=0.9 if not json_mode else 1.0,
                return_full_text=False,  # Exclude the input prompt to get clean generated response
            )
            res = outputs[0]["generated_text"].strip()
            # Clean template tokens if they bleed into generated output
            res = res.replace("<|im_end|>", "").replace("<|eot_id|>", "").strip()
            return res
        except Exception as e:
            logging.error(f"[RAG] Local model inference failed: {e}")
            raise e
            
    raise Exception("No Hugging Face client or local pipeline available.")

def get_chroma_client_and_collection():
    """Load local persistent ChromaDB collection."""
    global _chroma_client, _chroma_collection
    if _chroma_client is None or _chroma_collection is None:
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="jobhunter_jobs",
            metadata={"hnsw:space": "cosine"} # Use cosine similarity
        )
    return _chroma_client, _chroma_collection

def build_job_document(row: dict) -> str:
    """Format job record into structured text for vector search."""
    salary_str = "Not specified"
    if row.get('salary_min'):
        salary_str = f"£{row['salary_min']:.0f}"
        if row.get('salary_max') and row['salary_max'] != row['salary_min']:
            salary_str += f" - £{row['salary_max']:.0f}"

    text = (
        f"Title: {row.get('title', '')}\n"
        f"Company: {row.get('company', 'Unknown')}\n"
        f"Location: {row.get('location', 'Unknown')}, {row.get('country', 'Unknown')}\n"
        f"Workplace Type: {row.get('job_type', 'onsite')}\n"
        f"Contract Type: {row.get('contract_type', 'full-time')}\n"
        f"Seniority: {row.get('seniority', 'mid')}\n"
        f"Salary Range: {salary_str}\n"
        f"Required Skills: {row.get('skills', 'None')}\n"
        f"Description: {row.get('description', '')}"
    )
    return text

def index_new_jobs(reindex: bool = False):
    """
    Reads SQLite database and indexes jobs in ChromaDB.
    If reindex=False, skips already indexed job IDs.
    """
    logging.info("[RAG] Checking for jobs to index in ChromaDB...")
    client, collection = get_chroma_client_and_collection()

    # Fetch jobs from SQLite
    if not os.path.exists(DB_PATH):
        logging.info("[RAG] jobs.db not found. Skip indexing.")
        return

    # Delete expired jobs from ChromaDB
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM jobs WHERE datetime(coalesce(posted_at, scraped_at)) < datetime('now', '-30 days')")
        expired_ids = [str(r[0]) for r in c.fetchall()]
        conn.close()
        if expired_ids:
            # ChromaDB delete accepts a list of ids
            collection.delete(ids=expired_ids)
            logging.info(f"[RAG] Pruned {len(expired_ids)} expired jobs from ChromaDB.")
    except Exception as e:
        logging.info(f"[RAG] Error deleting expired jobs from Chroma: {e}")

    # Get already indexed IDs
    indexed_ids = set()
    if not reindex:
        try:
            results = collection.get(include=[])
            indexed_ids = set(results.get('ids', []))
        except Exception as e:
            logging.info(f"[RAG] Warning reading indexed IDs: {e}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = '''
        SELECT j.id, j.title, co.name AS company, j.location, j.country,
               j.job_type, j.contract_type, j.seniority, j.salary_min, j.salary_max,
               j.description,
               GROUP_CONCAT(s.name, ', ') AS skills
        FROM jobs j
        LEFT JOIN companies co ON j.company_id = co.id
        LEFT JOIN job_skills js ON j.id = js.job_id
        LEFT JOIN skills s ON js.skill_id = s.id
        WHERE datetime(coalesce(j.posted_at, j.scraped_at)) >= datetime('now', '-30 days')
        GROUP BY j.id
    '''
    c.execute(query)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Filter for new ones
    to_index = []
    for r in rows:
        job_id_str = str(r['id'])
        if reindex or job_id_str not in indexed_ids:
            to_index.append(r)

    if not to_index:
        logging.info(f"[RAG] Database up to date. 0 new jobs to index.")
        return

    logging.info(f"[RAG] Embedding and indexing {len(to_index)} jobs...")
    model = _get_embedding_model()

    # Batch inserts of 100
    batch_size = 100
    for idx in range(0, len(to_index), batch_size):
        batch = to_index[idx:idx+batch_size]
        
        ids = [str(r['id']) for r in batch]
        documents = [build_job_document(r) for r in batch]
        
        # Prefix passages with "passage: " for multilingual-e5-base
        prefixed_docs = [f"passage: {doc}" for doc in documents]
        embeddings = model.encode(prefixed_docs, show_progress_bar=False).tolist()
        
        metadatas = []
        for r in batch:
            metadatas.append({
                "job_id": r['id'],
                "country": r['country'] or "unknown",
                "job_type": r['job_type'] or "onsite",
                "seniority": r['seniority'] or "mid",
                "contract_type": r['contract_type'] or "full-time"
            })
            
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        logging.info(f"  Indexed batch {idx // batch_size + 1}/{-(-len(to_index) // batch_size)}")

    logging.info("[RAG] Indexing complete!")

def search_jobs(query_text: str, limit: int = 4) -> list[dict]:
    """Retrieve top matched jobs from vector store."""
    client, collection = get_chroma_client_and_collection()
    
    # Prefix query with "query: " for E5 model
    model = _get_embedding_model()
    query_embedding = model.encode([f"query: {query_text}"], show_progress_bar=False)[0].tolist()

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )
        
        # Reformat results
        output = []
        if results and 'documents' in results and len(results['documents'][0]) > 0:
            for i in range(len(results['documents'][0])):
                output.append({
                    "id": results['ids'][0][i],
                    "document": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "score": results['distances'][0][i]
                })
        return output
    except Exception as e:
        logging.info(f"[RAG] Search error: {e}")
        return []

def chat_with_coach(user_message: str, chat_history: list = None) -> str:
    """Main chatbot endpoint. Handles retrieval and LLM response generation using Hugging Face."""
    if chat_history is None:
        chat_history = []

    # Search jobs first to check distance score
    retrieved_jobs = search_jobs(user_message, limit=4)
    has_match = False
    context_str = "No active vacancy context matches this query."
    
    # Filter matches: if the closest match is close enough, inject them
    if retrieved_jobs and retrieved_jobs[0]['score'] < 0.85:
        has_match = True
        context_docs = []
        for idx, item in enumerate(retrieved_jobs):
            # Only include items that are reasonably similar
            if item['score'] < 0.85:
                similarity = round(1 - item['score'], 2)
                context_docs.append(
                    f"--- Matching Vacancy #{idx+1} (Semantic Match Score: {similarity}) ---\n"
                    f"{item['document']}\n"
                )
        if context_docs:
            context_str = "\n".join(context_docs)

    safe_msg = user_message.encode('ascii', errors='replace').decode('ascii')
    logging.info(f"[RAG] User Message: '{safe_msg}' | Has Database Match: {has_match}")

    # Construct messages list with chat history
    system_prompt = (
        "You are 'JobHunter's AI Career Assistant', a professional, encouraging, and expert career advisor for the JobHunter platform.\n"
        "You speak in a friendly blend of professional career guidance and warm Egyptian slang (اللغة العربية بلهجة مصرية عامية جميلة ومحببة) to make the user feel comfortable and welcome, unless the user writes in English, in which case you answer in English.\n\n"
        "Database Vacancies Context:\n"
        f"{context_str}\n\n"
        "Instructions:\n"
        "- If context is provided, refer to those job details directly to answer queries about what roles are open, where they are, or which companies are hiring. Treat them as live vacancies inside the JobHunter database.\n"
        "- If no context matches (or intent is COACHING), answer using your broad career advice knowledge. Explain concepts clearly.\n"
        "- Keep your responses structured, helpful, and concise. Avoid walls of text. Use bullet points where appropriate."
    )

    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history (last 6 messages to keep it short and preserve context)
    for msg in chat_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    messages.append({"role": "user", "content": user_message})

    try:
        response = _call_llm_hf(messages, temperature=0.7, max_tokens=1000, model_type='chat')
        return response
    except Exception as e:
        return f"يا خبر أبيض! حصلت مشكلة وأنا بحاول أكلم السيرفر: {e}"


def summarize_description(description: str) -> tuple[str, str]:
    """
    Summarize a job description using Hugging Face.
    Returns a tuple of (summary_en, summary_ar).
    Both summaries will be 2-3 simplified bullet points.
    summary_ar will be in a warm and friendly Egyptian Arabic slang.
    """
    if not description:
        return "", ""
    if isinstance(description, list):
        description = " ".join(str(item) for item in description)
    elif not isinstance(description, str):
        description = str(description)

    description = description.strip()
    if not description:
        return "", ""

    # Clean description briefly to avoid sending excessive junk
    cleaned_desc = description[:3000] # Limit input characters to save tokens

    prompt = f"""Summarize this job description in 2-3 sentences each.
Return ONLY a valid raw JSON object with exactly these two keys, no markdown, no extra text:
{{"summary_en": "...", "summary_ar": "..."}}

Job description:
{cleaned_desc}"""

    try:
        messages = [
            {"role": "system", "content": "You are a professional assistant that always outputs a valid raw JSON object with keys 'summary_en' and 'summary_ar'."},
            {"role": "user", "content": prompt}
        ]
        content = _call_llm_hf(messages, temperature=0.1, max_tokens=600, json_mode=True, model_type='summary')
        
        # Strip markdown fences and extract raw JSON object using regex
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
            
        import json
        try:
            # Clean common malformed JSON issues like trailing commas before parsing
            clean_content = re.sub(r',\s*\}', '}', content)
            clean_content = re.sub(r',\s*\]', ']', clean_content)
            data = json.loads(clean_content)
            summary_en_val = data.get("summary_en", "")
            summary_ar_val = data.get("summary_ar", "")
        except Exception as json_err:
            logging.info(f"[RAG] JSON parse failed: {json_err}. Falling back to regex extraction.")
            # Fallback to regex extraction
            def extract_field_regex(text: str, field: str) -> str:
                # Match: "field": "value" or 'field': 'value' or field: "value"
                m = re.search(r'[\'"]?' + field + r'[\'"]?\s*:\s*[\'"](.*?)[\'"]', text, re.DOTALL)
                if m:
                    return m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
                # Check list format with brackets
                m_arr = re.search(r'[\'"]?' + field + r'[\'"]?\s*:\s*\[(.*?)\]', text, re.DOTALL)
                if m_arr:
                    items = re.findall(r'[\'"](.*?)[\'"]', m_arr.group(1))
                    return "\n".join(f"- {i.strip()}" for i in items if i.strip())
                return ""
            summary_en_val = extract_field_regex(content, "summary_en")
            summary_ar_val = extract_field_regex(content, "summary_ar")

        if isinstance(summary_en_val, list):
            summary_en = "\n".join(f"- {str(item).strip()}" for item in summary_en_val if str(item).strip())
        else:
            summary_en = str(summary_en_val).strip()

        if isinstance(summary_ar_val, list):
            summary_ar = "\n".join(f"- {str(item).strip()}" for item in summary_ar_val if str(item).strip())
        else:
            summary_ar = str(summary_ar_val).strip()

        return summary_en, summary_ar
    except Exception as e:
        logging.error(f"[RAG] Error during description summarization: {e}")
        return "", ""


def analyze_cv_for_ats(cv_text: str) -> dict:
    """
    Analyze CV text for ATS compatibility deterministically and augment with LLM semantic summaries.
    Returns a merged dictionary using Hugging Face.
    """
    from ats_evaluator import evaluate_resume_ats
    
    # 1. Run local deterministic ATS scanner
    local_eval = evaluate_resume_ats(cv_text)
    
    # Setup default fallback data
    default_response = {
        "ats_score": local_eval["ats_score"],
        "detected_skills": local_eval["detected_skills"],
        "missing_skills": [],
        "feedback_en": local_eval["feedback_en"],
        "feedback_ar": local_eval["feedback_ar"],
        "summary_en": "Professional profile summary is loading...",
        "summary_ar": "الملخص المهني قيد المعالجة تلقائيًا..."
    }
    
    if not cv_text or not cv_text.strip():
        return default_response
        
    # 2. Call Hugging Face *only* for semantic candidate summary and missing skills gaps
    prompt = (
        "You are an expert recruitment advisor.\n"
        "Read the following candidate CV text and generate a structured JSON object (no markdown code blocks, no extra text) containing precisely these keys:\n"
        '- "missing_skills": a JSON array of 3-4 important technical skills missing from their CV that would make their profile stronger (e.g. ["Kubernetes", "PyTorch"]).\n'
        '- "summary_en": a brief 2-sentence summary of the candidate\'s profile in English (e.g. "Experienced Data Scientist with 5 years in machine learning...").\n'
        '- "summary_ar": a brief 2-sentence summary of the candidate\'s profile in a warm, encouraging Egyptian Arabic slang (لهجة مصرية عامية جميلة ومحببة).\n\n'
        f"CV Text to analyze:\n{cv_text[:4000]}"
    )
    
    messages = [
        {"role": "system", "content": "You are a professional resume parsing support system that always outputs a valid raw JSON object with keys: 'missing_skills', 'summary_en', 'summary_ar'."},
        {"role": "user", "content": prompt}
    ]

    try:
        content = _call_llm_hf(messages, temperature=0.1, max_tokens=600, json_mode=True, model_type='chat')
        
        # Strip markdown fences and extract raw JSON object using regex
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
            
        import json
        missing_skills = []
        summary_en = ""
        summary_ar = ""
        try:
            # Clean common malformed JSON issues like trailing commas before parsing
            clean_content = re.sub(r',\s*\}', '}', content)
            clean_content = re.sub(r',\s*\]', ']', clean_content)
            data = json.loads(clean_content)
            missing_skills = list(data.get("missing_skills", []))
            summary_en = str(data.get("summary_en", "")).strip()
            summary_ar = str(data.get("summary_ar", "")).strip()
        except Exception as json_err:
            logging.info(f"[RAG] CV ATS JSON parse failed: {json_err}. Falling back to regex extraction.")
            # Fallback to regex extraction
            def extract_field_regex(text: str, field: str) -> str:
                m = re.search(r'[\'"]?' + field + r'[\'"]?\s*:\s*[\'"](.*?)[\'"]', text, re.DOTALL)
                if m:
                    return m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
                return ""
            summary_en = extract_field_regex(content, "summary_en")
            summary_ar = extract_field_regex(content, "summary_ar")
            m_arr = re.search(r'[\'"]?missing_skills[\'"]?\s*:\s*\[(.*?)\]', content, re.DOTALL)
            if m_arr:
                missing_skills = [i.strip() for i in re.findall(r'[\'"](.*?)[\'"]', m_arr.group(1)) if i.strip()]

        # Merge LLM semantic content into local evaluation results
        local_eval["missing_skills"] = missing_skills if missing_skills else local_eval.get("missing_skills", [])
        if summary_en:
            local_eval["summary_en"] = summary_en
        if summary_ar:
            local_eval["summary_ar"] = summary_ar
        
        return local_eval
    except Exception as e:
        logging.info(f"[RAG] Error parsing LLM additions: {e}. Returning local evaluation.")
        return default_response


if __name__ == '__main__':
    # Standalone script to force reindexing
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--reindex', action='store_true', help='Reindex all jobs from database')
    args = parser.parse_args()
    
    # Load env variables for testing
    from dotenv import load_dotenv
    load_dotenv()
    
    index_new_jobs(reindex=args.reindex)
