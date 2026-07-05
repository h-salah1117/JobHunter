import os
import shutil
import logging
from huggingface_hub import HfApi, hf_hub_download

# Define database paths
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.db')

def _get_hf_config():
    """
    Returns (token, repo_id) if configured.
    Determines repo_id dynamically using SPACE_OWNER, SPACE_AUTHOR_NAME, SPACE_ID, or whoami.
    """
    token = os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")
    if not token:
        logging.info("[HF-Sync] HF_TOKEN is not configured in the environment. Skipping sync.")
        return None, None

    owner = os.getenv("SPACE_OWNER") or os.getenv("SPACE_AUTHOR_NAME")
    if not owner and os.getenv("SPACE_ID"):
        parts = os.getenv("SPACE_ID").split('/')
        if len(parts) > 0:
            owner = parts[0]
            logging.info(f"[HF-Sync] Resolved owner '{owner}' from SPACE_ID env var.")

    if not owner:
        # Fallback to fetching username via API
        try:
            api = HfApi()
            user_info = api.whoami(token=token)
            owner = user_info.get("name")
            logging.info(f"[HF-Sync] Fetched HF username '{owner}' via whoami.")
        except Exception as e:
            logging.warning(f"[HF-Sync] Failed to fetch Hugging Face username: {e}")
            return None, None

    if not owner:
        logging.warning("[HF-Sync] Could not determine repository owner.")
        return None, None

    # Construct dataset repo ID
    repo_id = f"{owner}/jobhunter-data"
    logging.info(f"[HF-Sync] Using Hugging Face dataset repository: {repo_id}")
    return token, repo_id


def download_db_from_hf() -> bool:
    """
    Downloads jobs.db from the user's private HF Dataset.
    Called on startup before initializing the database.
    """
    token, repo_id = _get_hf_config()
    if not token or not repo_id:
        logging.info("[HF-Sync] HF_TOKEN or owner configuration missing. Skipping DB download.")
        return False

    try:
        logging.info(f"[HF-Sync] Attempting to download jobs.db from HF dataset: {repo_id}...")
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename="jobs.db",
            repo_type="dataset",
            token=token
        )
        
        # Ensure target dir exists
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        
        # Copy to the target DB location
        shutil.copy(downloaded_path, DB_PATH)
        logging.info("[HF-Sync] jobs.db downloaded and restored successfully! 🎉")
        return True
    except Exception as e:
        logging.info(f"[HF-Sync] jobs.db not found on HF Hub (this is expected on first run): {e}")
        return False


def upload_db_to_hf() -> bool:
    """
    Uploads jobs.db to the user's private HF Dataset.
    Creates the repository if it doesn't already exist.
    """
    token, repo_id = _get_hf_config()
    if not token or not repo_id:
        logging.info("[HF-Sync] HF_TOKEN or owner configuration missing. Skipping DB upload.")
        return False

    if not os.path.exists(DB_PATH):
        logging.warning(f"[HF-Sync] jobs.db not found at {DB_PATH}. Nothing to upload.")
        return False

    try:
        api = HfApi()
        
        # Create private dataset repo if it doesn't exist
        logging.info(f"[HF-Sync] Ensuring private HF dataset repository exists: {repo_id}...")
        api.create_repo(
            repo_id=repo_id,
            token=token,
            repo_type="dataset",
            private=True,
            exist_ok=True
        )
        
        # Upload the SQLite database
        logging.info(f"[HF-Sync] Uploading jobs.db to HF dataset: {repo_id}...")
        api.upload_file(
            path_or_fileobj=DB_PATH,
            path_in_repo="jobs.db",
            repo_id=repo_id,
            repo_type="dataset",
            token=token
        )
        logging.info("[HF-Sync] jobs.db successfully backed up to Hugging Face! 🚀")
        return True
    except Exception as e:
        logging.error(f"[HF-Sync] Error backing up jobs.db: {e}")
        return False
