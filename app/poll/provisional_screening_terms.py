"""Small, explicit high-confidence username review policy.

Ordinary profanity is intentionally not represented here. These terms are
only used to send an application to human review; they never cause rejection.
"""

BLOCKED_BIGOTRY_TERMS = frozenset({
    'chink', 'coon', 'fag', 'kike', 'nigger', 'spic', 'tranny', 'wetback',
})
