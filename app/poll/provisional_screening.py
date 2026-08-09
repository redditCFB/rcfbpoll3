"""Deterministic, external-service-free screening for provisional applications."""
from dataclasses import dataclass
from enum import Enum
import os
import re
import unicodedata

from .provisional_screening_terms import BLOCKED_BIGOTRY_TERMS


class GateStatus(Enum):
    PASS = 'PASS'
    REVIEW = 'REVIEW'
    ERROR = 'ERROR'


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreeningResult:
    gates: tuple[GateResult, ...]
    flags: tuple[str, ...]

    @property
    def all_pass(self):
        return all(gate.status == GateStatus.PASS for gate in self.gates)


def normalize_username(username):
    normalized = unicodedata.normalize('NFKC', username).casefold()
    normalized = normalized.replace('_', '').replace('-', '')
    return normalized.translate(str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't'}))


def _levenshtein_at_most(left, right, maximum=1):
    if abs(len(left) - len(right)) > maximum:
        return False
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, 1):
        current = [index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[right_index] + 1,
                               previous[right_index - 1] + (left_char != right_char)))
        if min(current) > maximum:
            return False
        previous = current
    return previous[-1] <= maximum


def _contains_conservative_fuzzy(candidate, term):
    if len(term) < 6:
        return False
    for window_length in {len(term) - 1, len(term), len(term) + 1}:
        if window_length < 1 or window_length > len(candidate):
            continue
        for start in range(len(candidate) - window_length + 1):
            window = candidate[start:start + window_length]
            if _levenshtein_at_most(window, term):
                return True
    return False


def _contains_component(candidate, term, collision_words=()):
    if candidate == term:
        return True
    if candidate in collision_words:
        return False
    return term in candidate


def _contains_component_usage(username, normalized, term, collision_words=()):
    parts = [normalize_username(part) for part in re.split(r'[_-]+', username)]
    if any(_contains_component(part, term, collision_words) for part in parts):
        return True
    return term in normalized and not any(term in part for part in parts)


def screen_username(username):
    normalized = normalize_username(username)
    for blocked_term in BLOCKED_BIGOTRY_TERMS:
        term = blocked_term["value"]
        if blocked_term["match_mode"] == "component":
            if _contains_component_usage(
                    username, normalized, term, blocked_term["collision_words"]):
                return GateResult(GateStatus.REVIEW, ("bigoted_term",))
        elif term in normalized:
            return GateResult(GateStatus.REVIEW, ("bigoted_term",))
        elif blocked_term.get("allow_fuzzy") and _contains_conservative_fuzzy(normalized, term):
            return GateResult(GateStatus.REVIEW, ("bigoted_term",))
    return GateResult(GateStatus.PASS)


class ModeratorListUnavailable(ValueError):
    pass


class ModeratorProvider:
    def usernames(self):
        raise NotImplementedError


class EnvironmentModeratorProvider(ModeratorProvider):
    setting_name = 'RCFB_MODERATOR_USERNAMES'

    def usernames(self):
        raw = os.environ.get(self.setting_name)
        if raw is None or not raw.strip():
            raise ModeratorListUnavailable('Moderator list is not configured.')
        parts = [part.strip() for part in raw.split(',')]
        if any(not part or not re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts):
            raise ModeratorListUnavailable('Moderator list is malformed.')
        return tuple(parts)


def screen_moderator_reference(username, provider=None):
    try:
        moderator_names = (provider or EnvironmentModeratorProvider()).usernames()
    except ModeratorListUnavailable:
        return GateResult(GateStatus.ERROR, ("moderator_list_unavailable",))
    normalized = normalize_username(username)
    for moderator_name in moderator_names:
        moderator = normalize_username(moderator_name)
        if moderator == normalized:
            return GateResult(GateStatus.REVIEW, ("moderator_reference",))
        if len(moderator) >= 5 and moderator in normalized:
            return GateResult(GateStatus.REVIEW, ("moderator_reference",))
        if len(moderator) >= 8 and _contains_conservative_fuzzy(normalized, moderator):
            return GateResult(GateStatus.REVIEW, ("moderator_reference",))
    return GateResult(GateStatus.PASS)


class AccountAgeGate:
    def evaluate(self, username):
        return GateResult(GateStatus.PASS)


def screen_provisional_application(application, moderator_provider=None, account_age_gate=None):
    gates = (screen_username(application.user.username),
             screen_moderator_reference(application.user.username, moderator_provider),
             (account_age_gate or AccountAgeGate()).evaluate(application.user.username))
    flags = tuple(dict.fromkeys(flag for gate in gates for flag in gate.flags))
    return ScreeningResult(gates=gates, flags=flags)
