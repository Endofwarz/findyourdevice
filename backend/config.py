import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=False)

def _as_bool(v, default=False):
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","on"}

# existing
PHONES_CSV     = os.getenv("PHONES_CSV", "phones_clean_synthetic.csv")
USE_LLM        = _as_bool(os.getenv("USE_LLM"), False)
ALLOW_SCRAPERS = _as_bool(os.getenv("ALLOW_SCRAPERS"), False)
DEMO_SEED      = os.getenv("DEMO_SEED")

# resolve CSV path (absolute)
from pathlib import Path as _P
_csv = _P(PHONES_CSV)
PHONES_CSV = str(_csv if _csv.is_absolute() else (PROJECT_ROOT / _csv))


# Phase 3 flags
ALLOW_SCRAPERS = os.getenv("ALLOW_SCRAPERS", "0") == "1"
SCRAPER_ADMIN_TOKEN = os.getenv("SCRAPER_ADMIN_TOKEN", "")  # simple guard for manual triggers

# API keys (set only those you use)
BESTBUY_API_KEY = os.getenv("BESTBUY_API_KEY", "")
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")            # or OAuth if using Browse API
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")          # for phone-specs/GSM Arena proxies
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")            # optional Google Shopping
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")
EUR_PER_USD = 0.93 # Static exchange rate

# Cron cadence hint (minutes) for Render or external scheduler
INGEST_CADENCE_MIN = int(os.getenv("INGEST_CADENCE_MIN", "360"))

# NEW — LLM settings
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
LLM_BASE_URL   = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL_FINAL = os.getenv("LLM_MODEL_FINAL", "llama-3.3-70b-versatile")
LLM_MODEL_FAST  = os.getenv("LLM_MODEL_FAST",  "llama-3.1-8b-instant")
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "350"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))


