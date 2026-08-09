"""Small, explicit high-confidence username review policy.

Ordinary profanity is intentionally not represented here. These terms are
only used to send an application to human review; they never cause rejection.
"""

BLOCKED_BIGOTRY_TERMS = (
    {"value": "chink", "allow_substring": True, "allow_fuzzy": True},
    {"value": "coon", "allow_substring": False, "allow_fuzzy": False},
    {"value": "dyke", "allow_substring": False, "allow_fuzzy": False},
    {"value": "fag", "allow_substring": False, "allow_fuzzy": False},
    {"value": "faggot", "allow_substring": True, "allow_fuzzy": True},
    {"value": "gook", "allow_substring": False, "allow_fuzzy": False},
    {"value": "kike", "allow_substring": False, "allow_fuzzy": False},
    {"value": "nigger", "allow_substring": True, "allow_fuzzy": True},
    {"value": "paki", "allow_substring": False, "allow_fuzzy": False},
    {"value": "raghead", "allow_substring": True, "allow_fuzzy": True},
    {"value": "retard", "allow_substring": False, "allow_fuzzy": False},
    {"value": "spic", "allow_substring": False, "allow_fuzzy": False},
    {"value": "tranny", "allow_substring": True, "allow_fuzzy": True},
    {"value": "wetback", "allow_substring": True, "allow_fuzzy": True},
)
