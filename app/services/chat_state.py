import re
from threading import Lock
from time import monotonic

from app.services.common import (normalize_lecturer_name)

PENDING_SELECTIONS = {}


ACTIVE_LECTURERS = {}


SELECTION_LOCK = Lock()


SELECTION_TIMEOUT = 600  # 10 phút


def remember_active_lecturer(session_id, name):
    if not session_id:
        return

    with SELECTION_LOCK:
        ACTIVE_LECTURERS[session_id] = {
            "name": name,
            "expires_at": monotonic() + SELECTION_TIMEOUT,
        }


def get_active_lecturer(session_id):
    if not session_id:
        return None

    with SELECTION_LOCK:
        active = ACTIVE_LECTURERS.get(session_id)

        if not active:
            return None

        if active["expires_at"] <= monotonic():
            ACTIVE_LECTURERS.pop(session_id, None)
            return None

        return active["name"]


def save_pending_selection(session_id, question, candidates):
    if not session_id:
        return

    with SELECTION_LOCK:
        now = monotonic()

        for key, value in list(PENDING_SELECTIONS.items()):
            if value["expires_at"] <= now:
                del PENDING_SELECTIONS[key]

        if len(PENDING_SELECTIONS) >= 500:
            oldest = min(
                PENDING_SELECTIONS,
                key=lambda key: PENDING_SELECTIONS[key]["expires_at"],
            )
            del PENDING_SELECTIONS[oldest]

        PENDING_SELECTIONS[session_id] = {
            "question": question,
            "candidates": candidates,
            "expires_at": now + SELECTION_TIMEOUT,
        }


def get_pending_selection(session_id):
    if not session_id:
        return None

    with SELECTION_LOCK:
        pending = PENDING_SELECTIONS.get(session_id)

        if pending and pending["expires_at"] > monotonic():
            return pending

        PENDING_SELECTIONS.pop(session_id, None)
        return None


def clear_pending_selection(session_id):
    if session_id:
        with SELECTION_LOCK:
            PENDING_SELECTIONS.pop(session_id, None)


def choose_lecturer(message, candidates):
    text = normalize_lecturer_name(message)

    pattern = (
        r"(?:(?:em|toi|minh)\s+)?"
        r"(?:chon\s+)?"
        r"(?:(?:nguoi|thay|co|giang vien)\s+)?"
        r"(?:(?:thu|so)\s+)?"
        r"(\d+)"
    )

    number_match = re.fullmatch(pattern, text)

    if number_match:
        index = int(number_match.group(1)) - 1

        if 0 <= index < len(candidates):
            return candidates[index], True

        return None, True

    text = re.sub(r"^(?:thay|co|giang vien)\s+", "", text)

    matches = [
        lecturer
        for lecturer in candidates
        if (
            normalize_lecturer_name(lecturer["name"]) == text
            or f" {text} " in (
                f" {normalize_lecturer_name(lecturer['name'])} "
            )
        )
    ] if text else []

    if len(matches) == 1:
        return matches[0], True

    return None, bool(matches)


