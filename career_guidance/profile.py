"""Career profile model, validation, and prompt building."""

from dataclasses import asdict, dataclass

from career_guidance.models import InvalidInputError

EXPERIENCE_LEVELS = (
    "Student / No experience",
    "Junior (0-2 years)",
    "Mid-level (2-5 years)",
    "Senior (5+ years)",
)

_RESUME_EXCERPT_LENGTH = 1000


@dataclass(frozen=True)
class CareerProfile:
    """A user's career profile used to generate recommendations."""

    skills: str
    interests: str = ""
    education: str = ""
    experience_level: str = EXPERIENCE_LEVELS[0]
    goals: str = ""
    resume_text: str = ""

    def validate(self, min_length: int = 3, max_length: int = 10_000) -> None:
        """Validate the profile content.

        Raises:
            InvalidInputError: If required content is missing, too short, or too long.
        """
        core = f"{self.skills} {self.resume_text}".strip()
        if not core:
            raise InvalidInputError("Provide at least your skills or upload a resume.")
        if len(core) < min_length:
            raise InvalidInputError(
                f"Profile content must be at least {min_length} characters long."
            )
        if len(core) > max_length:
            raise InvalidInputError(
                f"Profile content must not exceed {max_length} characters."
            )

    def to_prompt_text(self) -> str:
        """Render the profile as text for a suggestion provider."""
        parts = [f"Skills: {self.skills.strip()}"]
        if self.interests.strip():
            parts.append(f"Interests: {self.interests.strip()}")
        if self.education.strip():
            parts.append(f"Education: {self.education.strip()}")
        parts.append(f"Experience level: {self.experience_level}")
        if self.goals.strip():
            parts.append(f"Career goals: {self.goals.strip()}")
        if self.resume_text.strip():
            parts.append(f"Resume:\n{self.resume_text.strip()}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Serialize for storage, truncating the resume to an excerpt."""
        data = asdict(self)
        if data["resume_text"]:
            data["resume_text"] = data["resume_text"][:_RESUME_EXCERPT_LENGTH]
        return data
