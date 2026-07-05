"""
run.py — Flask entry point.
Usage: python run.py
"""

from dotenv import load_dotenv
load_dotenv()

import os
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)
