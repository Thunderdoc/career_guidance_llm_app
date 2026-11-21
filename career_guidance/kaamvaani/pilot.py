"""Pilot-console helpers (Step 9.2): bulk worker onboarding.

A coordinator running a pilot camp knows workers by name and phone
number, not by account id — so bulk rows resolve by ``user_id`` OR
``phone``. Nothing here creates accounts: a row whose worker has no
account fails with a clear reason (A63). Rows are processed one by
one; a bad row fails and never fails the batch.
"""

from __future__ import annotations

import re

from career_guidance.kaamvaani.consent import ConsentStore, ConsentValidationError
from career_guidance.users import UserStore

#: Hard cap on rows per bulk request (keeps one request bounded).
MAX_BULK_ROWS = 100

#: Profile fields a bulk row may carry (anything else is a typo'd
#: column — the row fails rather than silently dropping data).
_ROW_FIELDS = (
    "skills",
    "education",
    "city",
    "district",
    "income_monthly",
    "income_text",
    "goal_type",
    "interests",
    "language",
)

_E164_RE = re.compile(r"\+[1-9]\d{7,14}")


def normalise_phone(raw: str) -> str:
    """Normalise a coordinator-typed phone number for the E.164
    lookup in the users table.

    Strips spaces, dashes and brackets. A bare 10-digit Indian
    mobile (starting 6–9) becomes ``+91…``; a leading ``91`` + 10
    digits becomes ``+91…``; an already-E.164 number passes
    through. Anything else passes through unchanged — the lookup
    then misses and the row fails with a clear error, never a
    guessed number."""
    phone = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if phone.startswith("+"):
        return phone
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    return phone


def bulk_onboard(store: ConsentStore, users: UserStore, rows: list[dict]) -> dict:
    """Save many worker profiles at once; returns per-row results.

    Each row needs ``user_id`` or ``phone`` plus any of the profile
    fields in ``_ROW_FIELDS``. ``created`` vs ``updated`` is decided
    by whether the worker already had a saved profile. A row that
    fails (no account, unknown field, invalid income, bad type)
    reports its reason and does not stop the batch.
    """
    if len(rows) > MAX_BULK_ROWS:
        raise ValueError(f"At most {MAX_BULK_ROWS} workers per request.")
    created = updated = failed = 0
    results: list[dict] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failed += 1
            results.append(
                {
                    "row": index,
                    "user_id": None,
                    "status": "failed",
                    "error": "Row is not an object.",
                }
            )
            continue
        user_id, error = _resolve_user_id(users, row)
        if error is not None:
            failed += 1
            results.append({"row": index, "user_id": user_id, "status": "failed", "error": error})
            continue
        assert user_id is not None
        unknown = sorted(set(row) - {"user_id", "phone"} - set(_ROW_FIELDS))
        if unknown:
            failed += 1
            results.append(
                {
                    "row": index,
                    "user_id": user_id,
                    "status": "failed",
                    "error": f"Unknown field(s): {', '.join(unknown)}.",
                }
            )
            continue
        fields = {name: row[name] for name in _ROW_FIELDS if name in row}
        try:
            existed = store.get_worker_profile(user_id) is not None
            store.save_worker_profile(user_id, **fields)
        except (ConsentValidationError, TypeError, ValueError) as exc:
            failed += 1
            results.append(
                {"row": index, "user_id": user_id, "status": "failed", "error": str(exc)}
            )
            continue
        if existed:
            updated += 1
            status = "updated"
        else:
            created += 1
            status = "created"
        results.append({"row": index, "user_id": user_id, "status": status, "error": None})
    return {"created": created, "updated": updated, "failed": failed, "results": results}


def _resolve_user_id(users: UserStore, row: dict) -> tuple[str | None, str | None]:
    """Resolve a bulk row to an account id, or (None, reason)."""
    user_id = row.get("user_id")
    if isinstance(user_id, str) and user_id.strip():
        user_id = user_id.strip()
        if users.get(user_id) is None:
            return None, f"No account with user id {user_id!r}."
        return user_id, None
    phone = row.get("phone")
    if isinstance(phone, str) and phone.strip():
        user = users.get_by_phone(normalise_phone(phone))
        if user is None:
            return None, f"No account with phone number {phone.strip()!r}."
        return user.id, None
    return None, "Row needs a user_id or a phone number."
