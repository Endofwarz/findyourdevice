# backend/prompts.py
def blurb_messages(intent: dict, facts: dict):
    sys = (
        "You are a concise shopping assistant. "
        "Write 2 short sentences (max ~70 words total) explaining WHY this phone fits the user's needs. "
        "Mention size match, battery, camera priority, OS/brand if relevant, and budget fit (within/over). "
        "No emojis, no bullets."
    )
    user = {"intent": intent, "phone": facts}
    return [{"role": "system", "content": sys},
            {"role": "user", "content": str(user)}]

def pros_cons_messages(intent: dict, facts: dict):
    sys = (
        "Return STRICT JSON: {\"pros\": [..3-5..], \"cons\": [..2-4..]} for this phone "
        "tailored to the user's needs. Keep each bullet short."
    )
    user = {"intent": intent, "phone": facts}
    return [{"role": "system", "content": sys},
            {"role": "user", "content": str(user)}]
