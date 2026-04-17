"""
core/store.py
=============
Centralised in-memory stores.

⚠️  Production note: replace both dicts with a Redis client
    (e.g. redis-py / aioredis) with a TTL of ~2 hours so that:
      • sessions survive server restarts
      • memory never leaks
      • multiple workers share state
"""

# Candidates who passed face-verification.
# { verify_token (str): { "candidate_name": str, "verified_at": str, "origin": str } }
VERIFIED_SESSIONS: dict = {}

# Active interview sessions.
# { session_id (str): {
#       "candidate_name":    str,
#       "face_verified":     bool,
#       "questions":         List[Question],
#       "ideal_answers":     { question_id (int): str },
#       "ordinal_to_uuid":   { ordinal_id (int): question_uuid (str) },  ← DB UUIDs
#       "created_at":        str,   ← ISO timestamp
#       "submitted":         bool,
#       "submitted_at":      str | None,
#   } }
SESSION_STORE: dict = {}
