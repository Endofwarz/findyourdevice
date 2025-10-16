# tools/sources/youtube.py
import os, time, requests
from typing import List, Tuple
from youtube_transcript_api import YouTubeTranscriptApi

API_KEY = os.getenv("YOUTUBE_API_KEY", "")

def top_video_ids(query: str, max_results: int = 3) -> List[str]:
    """
    Use YouTube Data API search to find top review videos (by view count).
    Returns a list of video IDs.
    """
    if not API_KEY:
        return []
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "maxResults": max_results,
        "key": API_KEY,
        # optional: filter for recent year
        # "publishedAfter": "2023-01-01T00:00:00Z",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])
    return [it["id"]["videoId"] for it in items]

def transcript_text(video_id: str) -> str:
    """
    Fetches plain transcript text. Returns "" if not available.
    """
    try:
        trs = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        return " ".join([t["text"] for t in trs])
    except Exception:
        return ""

def summarize_to_pros_cons(text: str) -> Tuple[List[str], List[str]]:
    """
    Very small heuristic summary to start with (no LLM required).
    We can upgrade to your Groq later.
    """
    t = (text or "").lower()
    pros, cons = [], []

    # quick keyword sniffing (add more as you like)
    if "battery" in t or "endurance" in t: pros.append("Good battery life")
    if "camera" in t or "photo" in t:      pros.append("Strong camera")
    if "display" in t or "screen" in t:    pros.append("Nice display")
    if "performance" in t or "speed" in t: pros.append("Fast performance")
    if "build" in t or "design" in t:      pros.append("Solid build quality")

    if "heavy" in t or "weight" in t:      cons.append("Feels heavy")
    if "price" in t or "expensive" in t:   cons.append("Pricey")
    if "overheat" in t or "hot" in t:      cons.append("Can get warm")
    if "bloat" in t or "bloatware" in t:   cons.append("Some bloatware")

    # trim
    return pros[:5], cons[:4]
