"""Personalization inputs and their versioned AI cache, independent of HTTP."""

import hashlib
import json

from app.config import get_settings
from app.integrations.ai import call_ai
from app.schemas import UserFocus
from app.services.generation_metadata import generation_versions


def focus_hash(membership):
    return hashlib.sha256(
        json.dumps(
            [
                membership.position_text,
                membership.interests,
                get_settings().ai_module,
                get_settings().ai_generation_version,
                generation_versions(),
            ],
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def derive_focus(db, membership):
    key = focus_hash(membership)
    if membership.focus_input_hash == key and membership.user_focus:
        return membership.user_focus
    focus = UserFocus.model_validate(
        call_ai("derive_user_focus", position_text=membership.position_text, interests=membership.interests)
    ).model_dump(mode="json")
    membership.focus_input_hash, membership.user_focus = (key, focus)
    return focus
