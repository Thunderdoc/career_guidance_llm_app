"""Suggestion providers: pluggable backends for career guidance.

Includes an offline demo provider (deterministic skill matching against a
curated career catalog) and an OpenAI-backed provider that returns
structured, schema-validated recommendations. Callers fall back to demo
mode when no API key is configured or the external service fails.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from career_guidance.config import Settings
from career_guidance.models import CareerRecommendation, CareerSuggestion, ProviderError
from career_guidance.profile import CareerProfile

logger = logging.getLogger("career_guidance.providers")

_SYSTEM_PROMPT = (
    "You are an experienced career counselor. Given a person's skills, "
    "resume summary, or interests, respond ONLY with a JSON array of "
    'exactly 5 objects, each with "title" and "rationale" string fields, '
    "recommending suitable career paths tailored to the person."
)

_RECOMMEND_SYSTEM_PROMPT = (
    "You are an expert career counselor. Based on the candidate profile, "
    "respond ONLY with a JSON array of exactly 5 objects, each with these "
    'fields: "title" (string), "match_reason" (string explaining why this '
    'career fits), "suitability" (one of: beginner, intermediate, advanced), '
    '"matching_skills" (array of skills the candidate already has), '
    '"missing_skills" (array of skills to acquire), "learning_path" '
    "(ordered array of learning milestones), and \"next_steps\" (array of "
    "practical short-term actions such as projects or certifications)."
)

_ALLOWED_SUITABILITY = {"beginner", "intermediate", "advanced"}


class SuggestionProvider(ABC):
    """Interface every suggestion backend must implement."""

    name: str = "base"
    is_demo: bool = False

    @abstractmethod
    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        """Return simple career suggestions for the given profile text."""

    @abstractmethod
    def recommend(self, profile: CareerProfile) -> list[CareerRecommendation]:
        """Return structured career recommendations for the given profile."""


@dataclass(frozen=True)
class _CareerTemplate:
    title: str
    blurb: str
    skills: tuple[str, ...]
    learning_path: tuple[str, ...]
    next_steps: tuple[str, ...]


_CAREER_CATALOG: tuple[_CareerTemplate, ...] = (
    _CareerTemplate(
        title="Software Developer",
        blurb="Builds applications and services across the stack.",
        skills=("python", "javascript", "git", "sql", "api", "testing"),
        learning_path=(
            "Master one core language deeply (e.g. Python or JavaScript)",
            "Learn version control, code review, and testing practices",
            "Build and deploy a full-stack project end to end",
        ),
        next_steps=(
            "Publish 2-3 projects on GitLab/GitHub with clean READMEs",
            "Contribute a small fix to an open-source project",
            "Practice data structures and algorithms weekly",
        ),
    ),
    _CareerTemplate(
        title="Data Analyst",
        blurb="Turns raw data into decisions with analysis and dashboards.",
        skills=("python", "sql", "excel", "statistics", "visualization", "pandas"),
        learning_path=(
            "Get fluent in SQL joins, aggregations, and window functions",
            "Learn pandas and a BI/visualization tool",
            "Study basic statistics and A/B testing",
        ),
        next_steps=(
            "Analyze a public dataset and publish the notebook",
            "Build one interactive dashboard portfolio piece",
            "Practice SQL interview questions",
        ),
    ),
    _CareerTemplate(
        title="QA Engineer",
        blurb="Safeguards product quality through systematic testing.",
        skills=("testing", "automation", "selenium", "python", "api", "ci/cd"),
        learning_path=(
            "Learn test design techniques and bug reporting",
            "Automate UI and API tests (e.g. Playwright/Selenium + pytest)",
            "Integrate test suites into CI pipelines",
        ),
        next_steps=(
            "Write an automated test suite for one of your projects",
            "Learn to read and triage CI failures",
            "Study ISTQB foundation topics",
        ),
    ),
    _CareerTemplate(
        title="Technical Writer",
        blurb="Explains complex systems through clear documentation.",
        skills=("writing", "documentation", "communication", "markdown", "api"),
        learning_path=(
            "Study documentation frameworks (tutorials, how-tos, reference)",
            "Learn Markdown, docs-as-code, and style guides",
            "Practice documenting APIs and developer workflows",
        ),
        next_steps=(
            "Write a full README + user guide for an open-source project",
            "Build a small documentation portfolio site",
            "Join a docs-focused open-source community",
        ),
    ),
    _CareerTemplate(
        title="UX/UI Designer",
        blurb="Designs intuitive, user-centered product experiences.",
        skills=("design", "figma", "user research", "prototyping", "css"),
        learning_path=(
            "Learn UX fundamentals: research, personas, user flows",
            "Master a design tool (Figma) and prototyping",
            "Study accessibility and design systems",
        ),
        next_steps=(
            "Redesign an existing app screen and document your reasoning",
            "Create 2-3 case studies for a portfolio",
            "Run a usability test with 3-5 people",
        ),
    ),
    _CareerTemplate(
        title="Product Support Specialist",
        blurb="Helps users succeed and feeds insights back to product teams.",
        skills=("communication", "troubleshooting", "empathy", "documentation", "sql"),
        learning_path=(
            "Learn a support/ticketing workflow and SLAs",
            "Build product debugging and log-reading skills",
            "Practice writing clear, empathetic responses",
        ),
        next_steps=(
            "Answer questions in a community forum for a product you know",
            "Write three troubleshooting guides",
            "Learn basic SQL to investigate user issues",
        ),
    ),
)


def _suitability_for(experience_level: str) -> str:
    level = experience_level.lower()
    if "senior" in level:
        return "advanced"
    if "mid" in level:
        return "intermediate"
    return "beginner"


class MockProvider(SuggestionProvider):
    """Offline provider using deterministic skill matching (demo mode)."""

    name = "Offline skill matching (demo)"
    is_demo = True

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        return [
            CareerSuggestion(title=career.title, rationale=career.blurb)
            for career in _CAREER_CATALOG[:5]
        ]

    def recommend(self, profile: CareerProfile) -> list[CareerRecommendation]:
        text = profile.to_prompt_text().lower()
        suitability = _suitability_for(profile.experience_level)
        scored: list[tuple[int, CareerRecommendation]] = []
        for career in _CAREER_CATALOG:
            matching = [skill for skill in career.skills if skill in text]
            missing = [skill for skill in career.skills if skill not in text]
            reason = (
                f"{career.blurb} Your profile already covers "
                f"{len(matching)} of {len(career.skills)} key skills for this path."
            )
            scored.append(
                (
                    len(matching),
                    CareerRecommendation(
                        title=career.title,
                        match_reason=reason,
                        suitability=suitability,
                        matching_skills=matching,
                        missing_skills=missing,
                        learning_path=list(career.learning_path),
                        next_steps=list(career.next_steps),
                    ),
                )
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [recommendation for _, recommendation in scored[:5]]


class OpenAIProvider(SuggestionProvider):
    """Provider backed by the OpenAI API with schema-validated output."""

    name = "OpenAI"
    is_demo = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _complete(self, system_prompt: str, user_content: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - env specific
            raise ProviderError("The 'openai' package is not installed.") from error
        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                timeout=self._settings.openai_timeout_seconds,
            )
            response = client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as error:
            raise ProviderError(f"OpenAI request failed: {error}") from error

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        payload = self._complete(_SYSTEM_PROMPT, profile_text)
        return _parse_suggestions(payload)

    def recommend(self, profile: CareerProfile) -> list[CareerRecommendation]:
        payload = self._complete(_RECOMMEND_SYSTEM_PROMPT, profile.to_prompt_text())
        return _parse_recommendations(payload)


def _strip_code_fence(payload: str) -> str:
    cleaned = payload.strip()
    if cleaned.startswith("```"):
        start, end = cleaned.find("["), cleaned.rfind("]")
        cleaned = cleaned[start : end + 1] if start != -1 and end != -1 else cleaned
    return cleaned


def _parse_suggestions(payload: str) -> list[CareerSuggestion]:
    """Parse a JSON array of simple suggestions from a model response."""
    try:
        data = json.loads(_strip_code_fence(payload))
        suggestions = [
            CareerSuggestion(title=str(item["title"]), rationale=str(item["rationale"]))
            for item in data
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ProviderError("Could not parse the AI response.") from error
    if not suggestions:
        raise ProviderError("The AI response contained no suggestions.")
    return suggestions


def _normalize_suitability(value: object) -> str:
    text = str(value).strip().lower()
    return text if text in _ALLOWED_SUITABILITY else "beginner"


def _parse_recommendations(payload: str) -> list[CareerRecommendation]:
    """Parse and validate a JSON array of structured recommendations."""
    try:
        data = json.loads(_strip_code_fence(payload))
        recommendations = [
            CareerRecommendation(
                title=str(item["title"]),
                match_reason=str(item["match_reason"]),
                suitability=_normalize_suitability(item.get("suitability", "beginner")),
                matching_skills=[str(s) for s in item.get("matching_skills", [])],
                missing_skills=[str(s) for s in item.get("missing_skills", [])],
                learning_path=[str(s) for s in item.get("learning_path", [])],
                next_steps=[str(s) for s in item.get("next_steps", [])],
            )
            for item in data
        ]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
        raise ProviderError("Could not parse the AI recommendation response.") from error
    if not recommendations:
        raise ProviderError("The AI response contained no recommendations.")
    return recommendations


def get_provider(settings: Settings) -> SuggestionProvider:
    """Select the provider based on configuration."""
    if settings.openai_api_key:
        return OpenAIProvider(settings)
    logger.info("No OPENAI_API_KEY configured; using offline demo provider")
    return MockProvider()
