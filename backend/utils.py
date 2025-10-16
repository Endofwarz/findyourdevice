import os, re, pathlib

def slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def ensure_dirs(paths):
    for p in paths:
        pathlib.Path(p).mkdir(parents=True, exist_ok=True)
