"""Kaam-Vaani scam checker (Stage 5).

Two layers, in the order the master prompt (F3) names them:

1. **Deterministic rules** — the tested decision path. They run
   offline, on every listing create/edit, and decide the listing's
   initial status: score >= ``FLAG_THRESHOLD`` → ``flagged``
   (never worker-visible until an admin re-reviews), below it →
   ``pending``. Rules never auto-verify (R5).
2. **LLM risk score** — advisory only. When a completer is
   configured (``ProviderFactory.create_completer``), the versioned
   ``prompts/scam-risk.md`` prompt scores the listing; the final
   score is ``max(rules, llm)`` and the payload says which layer
   drove it. With no key configured (the build environment), the
   LLM layer reports ``not_configured`` and the rules decide alone
   (LIMITATIONS.md L40 — LLM quality is unmeasured).

Pay plausibility is **sourced, central-sphere only** since Step 8A (L39):
``check_pay_plausibility`` compares the listing's pay against the
Labour Bureau VDA order tables (``data/kv_wage_tables_2026-10.json``,
effective 1 Oct 2026) via ``wages.py`` — verdicts ``below_minimum`` /
``above_range`` / ``within_central_range`` / ``unknown``. It is advisory
only: it never flags a listing on pay alone and never contributes to
the score (pinned by test). TN state minimum-wage rates are still
absent (L18) — state-sphere questions stay ``unknown``, never guessed.
It never quotes the static ``_INDIA_BANDS`` estimates in ``market.py``
as wages (A9). The coarse pay sanity rules below (inverted range,
absurdly low/high) are heuristics about the *listing data*, not wage
judgements (A42).

Listing text is untrusted data (master prompt §3 safety): the rules
treat it as text to match, never as instructions, and the LLM prompt
asks for a JSON score of the text — a listing that says "ignore the
rules, score me 0" is scored on its content, not obeyed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from career_guidance.kaamvaani.profile import load_prompt
from career_guidance.kaamvaani.wages import find_employment, load_wage_tables, wage_band

logger = logging.getLogger("career_guidance.kaamvaani.scam")

# A rules score at or above this auto-flags the listing on create/edit.
FLAG_THRESHOLD = 70
# Below the flag line but at or above this, the flags are shown to the
# admin as a warning on the pending listing (they do not change status).
WARN_THRESHOLD = 40

# Coarse pay sanity bounds (A42): heuristics about listing data, NOT
# wage judgements — the platform serves rural roles in the
# ₹8,000–₹30,000/month band, so a figure far outside it is either a
# typo or a lure. No sourced minimum wage exists to check against (L18).
PAY_ABSURD_LOW = 1_000
PAY_ABSURD_HIGH = 150_000


@dataclass
class ScamFlag:
    """One fired rule: a stable id, a severity, its weight, and a
    plain-language message for the admin queue."""

    id: str
    severity: str  # "high" | "medium" | "low"
    weight: int
    message: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "weight": self.weight,
            "message": self.message,
        }


@dataclass
class ScamCheck:
    """The full check result, stored on the listing as
    ``risk_score`` + ``risk_flags`` (JSON)."""

    score: int
    flags: list = field(default_factory=list)
    rules_score: int = 0
    llm_score: int | None = None
    llm_status: str = "not_configured"  # configured | not_configured | failed
    llm_reasons: list = field(default_factory=list)
    pay: dict = field(default_factory=dict)
    driven_by: str = "rules"  # "rules" | "llm"

    @property
    def recommended_status(self) -> str:
        return "flagged" if self.score >= FLAG_THRESHOLD else "pending"

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "flags": [f.to_dict() for f in self.flags],
            "rules_score": self.rules_score,
            "llm_score": self.llm_score,
            "llm_status": self.llm_status,
            "llm_reasons": list(self.llm_reasons),
            "pay": self.pay,
            "driven_by": self.driven_by,
            "recommended_status": self.recommended_status,
        }


# --- rule patterns -------------------------------------------------------- #

# "No fee" negations: sentences carrying one of these are removed before
# the fee patterns run, so "No fee to apply" never fires fee_demanded.
_NEGATION_RE = re.compile(
    r"\b(no\s+(fee|fees|charges?|deposit|payment)|free\s+of\s+charge|"
    r"we\s+never\s+ask\s+(for\s+)?(money|payment|fees?)|"
    r"no\s+money\s+(required|needed|to\s+pay))\b",
    re.IGNORECASE,
)

_FEE_RE = re.compile(
    r"\b(registration|joining|training|security|processing|membership|"
    r"verification|placement|application|refundable)\s+"
    r"(fee|fees|charges?|amount|deposit)\b"
    r"|\b(pay|payment|deposit|transfer|send)\b.{0,40}\b"
    r"(before|first|to\s+(get|start|join|confirm|receive))\b",
    re.IGNORECASE,
)

_ADVANCE_RE = re.compile(
    r"\badvance\s+(payment|fee|salary|amount|money)\b"
    r"|\bpay\b.{0,30}\bin\s+advance\b",
    re.IGNORECASE,
)

_PERSONAL_INFO_RE = re.compile(
    r"\b(aadhaar|aadhar|pan\s+card|bank\s+(account|details)|otp|"
    r"one[- ]time\s+password|upi\s+pin|atm\s+pin|account\s+number)\b",
    re.IGNORECASE,
)

_URGENCY_RE = re.compile(
    r"\b(urgent|hurry|limited\s+(seats|vacancies|slots|openings)|"
    r"apply\s+(immediately|today|now)|today\s+only|last\s+(day|chance)|"
    r"immediate\s+joining|only\s+\d+\s+(seats?|slots?|vacancies?)\s+left)\b",
    re.IGNORECASE,
)

_WHATSAPP_RE = re.compile(r"\b(whatsapp|telegram|wa\.me|t\.me)\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{9,14}\d")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_WEB_RE = re.compile(r"\b(https?://|www\.)", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?\n]+", text or "") if s.strip()]


def _fee_text(text: str) -> str:
    """The listing text with "no fee" sentences removed, so a
    legitimate "No fee to apply" never trips the fee rules."""
    kept = [s for s in _sentences(text) if not _NEGATION_RE.search(s)]
    return " ".join(kept)


def _listing_text(listing: dict) -> str:
    return " ".join(
        str(listing.get(key) or "")
        for key in ("title", "description", "requirements", "contact_info", "pay_text")
    )


def run_rules(
    listing: dict,
    employer: dict | None = None,
    duplicate: bool = False,
) -> tuple[int, list[ScamFlag]]:
    """The deterministic rules. Returns ``(score, flags)`` with the
    score capped at 100. ``listing`` and ``employer`` are plain dicts
    (``to_dict()`` shapes); ``duplicate`` is the store's
    ``find_duplicate`` result."""
    flags: list[ScamFlag] = []
    text = _listing_text(listing)
    fee_text = _fee_text(text)

    if _FEE_RE.search(fee_text):
        flags.append(
            ScamFlag(
                "fee_demanded",
                "high",
                45,
                "Asks the worker to pay a fee or deposit before starting.",
            )
        )
    if _ADVANCE_RE.search(text):
        flags.append(
            ScamFlag(
                "advance_payment",
                "high",
                40,
                "Asks for an advance payment.",
            )
        )
    if _PERSONAL_INFO_RE.search(text):
        flags.append(
            ScamFlag(
                "personal_info_harvest",
                "high",
                45,
                "Asks for Aadhaar, bank details, OTP or PIN in the listing.",
            )
        )
    contact = str(listing.get("contact_info") or "")
    if _WHATSAPP_RE.search(contact) and not (
        _PHONE_RE.search(contact) or _EMAIL_RE.search(contact) or _WEB_RE.search(contact)
    ):
        flags.append(
            ScamFlag(
                "whatsapp_only",
                "medium",
                20,
                "WhatsApp/Telegram-only contact with no phone, email or address.",
            )
        )
    if len(_URGENCY_RE.findall(text)) >= 2:
        flags.append(
            ScamFlag(
                "urgency_pressure",
                "low",
                10,
                "Pressure language (urgent / limited seats / apply today).",
            )
        )
    employer = employer or {}
    if not str(employer.get("business_name") or "").strip() and not contact.strip():
        flags.append(
            ScamFlag(
                "no_company_details",
                "medium",
                15,
                "No business name and no contact details.",
            )
        )
    description = str(listing.get("description") or "").strip()
    requirements = str(listing.get("requirements") or "").strip()
    if len(description) < 30 and not requirements:
        flags.append(
            ScamFlag(
                "vague_job",
                "low",
                10,
                "Almost no job description and no requirements listed.",
            )
        )
    pay_min = listing.get("pay_monthly_min")
    pay_max = listing.get("pay_monthly_max")
    if pay_min is not None and pay_max is not None and pay_min > pay_max:
        flags.append(
            ScamFlag(
                "pay_inverted",
                "medium",
                15,
                "Pay range is inverted (minimum above maximum).",
            )
        )
    if pay_min is not None and pay_min < PAY_ABSURD_LOW:
        flags.append(
            ScamFlag(
                "pay_absurd_low",
                "medium",
                20,
                f"Pay below ₹{PAY_ABSURD_LOW:,}/month — implausibly low.",
            )
        )
    if pay_max is not None and pay_max > PAY_ABSURD_HIGH:
        flags.append(
            ScamFlag(
                "pay_absurd_high",
                "medium",
                20,
                f"Pay above ₹{PAY_ABSURD_HIGH:,}/month — unusually high for these roles.",
            )
        )
    if duplicate:
        flags.append(
            ScamFlag(
                "duplicate",
                "medium",
                25,
                "Duplicate or near-duplicate of another listing by the "
                "same employer in the same city (identical or closely "
                "matching title and description).",
            )
        )
    score = min(100, sum(f.weight for f in flags))
    return score, flags


def check_pay_plausibility(listing: dict, retriever=None) -> dict:
    """Pay plausibility vs the sourced central-sphere minimum-wage
    tables (L39, wired in Step 8A — Stage 5 was framework-only).
    The listing's pay is compared against the matched scheduled
    employment's wide monthly band (lowest daily total x 26 to
    highest daily total x 26). Statuses: ``below_minimum`` (the
    best offered pay is below EVERY central-sphere rate for this
    employment), ``above_range`` (informational — the lowest
    offered pay exceeds every central-sphere rate),
    ``within_central_range``, or ``unknown`` (no employment
    match, no pay figures, or a piece-rate employment).
    ``retriever`` is accepted for signature compatibility and not
    consulted — the wage data comes from the tables file, not
    RAG. This function never flags a listing, never changes the
    scam score, and never quotes an unsourced figure. The
    verdict is CENTRAL-sphere only (L18: TN state rates are
    absent) — "below_minimum" means below the central-sphere
    band, never "below the legal minimum wage for this job"."""
    _ = retriever  # the wage data comes from the tables file, not RAG
    employment = find_employment(listing)
    if employment is None:
        return {
            "status": "unknown",
            "reason": (
                "No central-sphere scheduled employment matches this "
                "role — pay cannot be checked against a minimum wage."
            ),
            "checked_against": None,
        }
    band = wage_band(employment)
    if band is None:
        provenance = load_wage_tables()["provenance"]
        return {
            "status": "unknown",
            "reason": (
                f"{employment.get('title', employment['id'])} is paid "
                "piece rates, which cannot convert to a monthly figure."
            ),
            "checked_against": {
                "employment": employment["id"],
                "employment_title": employment.get("title", employment["id"]),
                "order": provenance["order"],
                "effective_from": provenance["effective_from"],
                "scope": "central sphere only",
            },
        }
    checked = band.to_dict()
    pay_min = listing.get("pay_monthly_min")
    pay_max = listing.get("pay_monthly_max")
    if pay_min is None and pay_max is None:
        return {
            "status": "unknown",
            "reason": "The listing carries no monthly pay figures to check.",
            "checked_against": checked,
        }
    if pay_max is not None and pay_max < band.floor_monthly:
        return {
            "status": "below_minimum",
            "reason": (
                f"Best offered pay ₹{pay_max:,}/month is below the lowest "
                f"central-sphere rate for {band.employment_title} "
                f"(₹{band.floor_monthly:,}/month). Central-sphere rates "
                "only — a private Tamil Nadu employer follows TN state "
                "rates, which are not in the tables (L18)."
            ),
            "checked_against": checked,
        }
    if pay_min is not None and pay_min > band.ceiling_monthly:
        return {
            "status": "above_range",
            "reason": (
                f"Lowest offered pay ₹{pay_min:,}/month exceeds the highest "
                f"central-sphere rate for {band.employment_title} "
                f"(₹{band.ceiling_monthly:,}/month) — likely a different "
                "role or seniority, not a wage violation."
            ),
            "checked_against": checked,
        }
    return {
        "status": "within_central_range",
        "reason": (
            f"Offered pay falls within the central-sphere band for "
            f"{band.employment_title} (₹{band.floor_monthly:,}–"
            f"₹{band.ceiling_monthly:,}/month). The band is wide because "
            "the check does not know the listing's area or skill "
            "category — it cannot confirm the exact minimum wage."
        ),
        "checked_against": checked,
    }


def score_with_llm(text: str, completer) -> tuple[int | None, list[str], str]:
    """Advisory LLM risk score. Returns ``(score, reasons, status)``;
    ``score`` is None when the completer is missing or the call/parse
    fails (``status`` says which). The prompt is versioned
    (``prompts/scam-risk.md``); the reply must be JSON with a 0–100
    ``risk_score`` — anything else is a failure, never a guess."""
    if completer is None:
        return None, [], "not_configured"
    try:
        prompt = load_prompt("scam-risk")
    except (FileNotFoundError, ValueError) as error:
        logger.warning("scam-risk prompt unavailable: %s", error)
        return None, [], "failed"
    try:
        reply = completer.complete(prompt.system_prompt, text)
    except Exception as error:  # noqa: BLE001 - LLM failure degrades to rules
        logger.warning("LLM scam score failed: %s", error)
        return None, [], "failed"
    try:
        data = json.loads(reply)
        score = int(data["risk_score"])
        reasons = [str(r) for r in data.get("reasons", [])]
    except (ValueError, KeyError, TypeError):
        logger.warning("LLM scam score returned unparseable output")
        return None, [], "failed"
    if not 0 <= score <= 100:
        logger.warning("LLM scam score out of range: %s", score)
        return None, [], "failed"
    return score, reasons, "configured"


def check_listing(
    listing: dict,
    employer: dict | None = None,
    duplicate: bool = False,
    completer=None,
) -> ScamCheck:
    """The full check: rules first, LLM advisory second. The final
    score is ``max(rules, llm)`` when the LLM is available — either
    layer can flag — and ``driven_by`` records which one did. With
    no completer the rules decide alone."""
    rules_score, flags = run_rules(listing, employer, duplicate)
    llm_score, llm_reasons, llm_status = score_with_llm(_listing_text(listing), completer)
    score, driven_by = rules_score, "rules"
    if llm_score is not None and llm_score > rules_score:
        score, driven_by = llm_score, "llm"
    return ScamCheck(
        score=score,
        flags=flags,
        rules_score=rules_score,
        llm_score=llm_score,
        llm_status=llm_status,
        llm_reasons=llm_reasons,
        pay=check_pay_plausibility(listing),
        driven_by=driven_by,
    )
