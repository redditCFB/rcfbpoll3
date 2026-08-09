"""Small, explicit high-confidence username review policy.

Ordinary profanity is intentionally not represented here. These terms are
only used to send an application to human review; they never cause rejection.
"""

BLOCKED_BIGOTRY_TERMS = (
    {"value": "chink", "match_mode": "substring", "allow_fuzzy": True},
    {"value": "coon", "match_mode": "component", "collision_words": ("raccoon",)},
    {"value": "dyke", "match_mode": "component", "collision_words": ()},
    {"value": "fag", "match_mode": "component", "collision_words": ()},
    {"value": "faggot", "match_mode": "substring", "allow_fuzzy": True},
    {"value": "gook", "match_mode": "component", "collision_words": ()},
    {"value": "kike", "match_mode": "component", "collision_words": ()},
    {"value": "nigger", "match_mode": "substring", "allow_fuzzy": True},
    {"value": "paki", "match_mode": "component", "collision_words": ()},
    {"value": "raghead", "match_mode": "substring", "allow_fuzzy": True},
    {"value": "retard", "match_mode": "component", "collision_words": ()},
    {"value": "spic", "match_mode": "component", "collision_words": ("spicy", "spice")},
    {"value": "tranny", "match_mode": "substring", "allow_fuzzy": True},
    {"value": "wetback", "match_mode": "substring", "allow_fuzzy": True},
)
