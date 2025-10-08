import os
from dotenv import load_dotenv

load_dotenv()  # loads backend/.env

def _as_bool(v, default=False):
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","on"}

PHONES_CSV     = os.getenv("PHONES_CSV", "../data/phones_clean_synthetic.csv")
USE_LLM        = _as_bool(os.getenv("USE_LLM"), False)
ALLOW_SCRAPERS = _as_bool(os.getenv("ALLOW_SCRAPERS"), False)
DEMO_SEED      = os.getenv("DEMO_SEED")