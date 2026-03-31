"""
mjr/schema.py
-------------
Dataclasses and validation for the Master Job Repository (MJR).

The MJR is a YAML file that serves as the persistent, structured record of a
person's professional identity. It is written once by the builder, read by the
job analyst, and incrementally updated by the resume coach.

Two fields are strictly immutable after initial extraction:
  - bullet.original  (the exact text from the source resume)
  - bullet.id        (used as a stable foreign key across coaching sessions)

Everything else — coached variants, scores, categories — can be updated.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# PM Skill Categories
# The 7 dimensions used to classify every bullet in the MJR.
# The job analyst uses these to match bullets to JD must-haves.
# ---------------------------------------------------------------------------

PM_SKILL_CATEGORIES = [
    "product_design_and_development",
    "leadership_and_execution",
    "strategy_and_planning",
    "business_and_marketing",
    "project_management",
    "technical_and_analytical",
    "communication",
]


# ---------------------------------------------------------------------------
# JD Role Types
# Auto-assigned by the job analyst. Used to tag coached variants so they
# can be retrieved without user input on future runs.
# ---------------------------------------------------------------------------

JD_ROLE_TYPES = [
    "growth-pm",
    "platform-pm",
    "ai-pm",
    "enterprise-pm",
    "consumer-pm",
    "data-pm",
    "founding-pm",
    "operations",
    "strategy",
    "general-pm",
]


@dataclass
class CoachedVariant:
    """
    A single coaching output for one bullet, tied to a specific role context.

    The job analyst assigns `role_type` automatically based on JD analysis,
    so the user never has to categorize it manually. On future runs, the coach
    checks for an existing variant with a matching role_type before starting
    a new session.
    """
    role_type: str                    # One of JD_ROLE_TYPES
    text: str                         # The enhanced bullet text
    coaching_date: str                # ISO date string
    jd_source: Optional[str] = None  # Filename or URL of the JD that triggered this


@dataclass
class Bullet:
    """
    A single accomplishment bullet from the user's resume.

    `original` is immutable — it is set once during extraction and never
    overwritten. `coached_variants` accumulates over time as the user applies
    to different roles. The coach always checks existing variants first.
    """
    id: str                                        # Stable UUID — do not change after creation
    original: str                                  # Exact text from resume — never modified
    categories: list[str] = field(default_factory=list)  # Subset of PM_SKILL_CATEGORIES
    strength_score: Optional[float] = None         # 0.0–1.0, set by job analyst
    coached_variants: list[CoachedVariant] = field(default_factory=list)

    @staticmethod
    def new(original: str, categories: list[str] = None) -> "Bullet":
        return Bullet(
            id=str(uuid.uuid4())[:8],
            original=original,
            categories=categories or [],
        )

    def get_variant_for(self, role_type: str) -> Optional[CoachedVariant]:
        """Return the coached variant for a given role type, if one exists."""
        for v in self.coached_variants:
            if v.role_type == role_type:
                return v
        return None


@dataclass
class Experience:
    company: str
    title: str
    start_date: str
    end_date: Optional[str]           # None if current role
    is_current: bool = False
    description: Optional[str] = None
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class Education:
    institution: str
    degree: str
    field: str
    graduation_year: Optional[int] = None


@dataclass
class PersonalInfo:
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None


@dataclass
class MasterJobRepository:
    """
    The top-level MJR object. Serialized to and deserialized from mjr.yaml.

    Usage:
        mjr = MasterJobRepository.from_yaml("mjr.yaml")
        mjr.save("mjr.yaml")
    """
    personal: PersonalInfo
    experiences: list[Experience] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)

    def all_bullets(self) -> list[tuple[str, Bullet]]:
        """Return all bullets across all experiences as (company, bullet) tuples."""
        result = []
        for exp in self.experiences:
            for bullet in exp.bullets:
                result.append((exp.company, bullet))
        return result

    def get_bullet_by_id(self, bullet_id: str) -> Optional[Bullet]:
        for _, bullet in self.all_bullets():
            if bullet.id == bullet_id:
                return bullet
        return None

    def save(self, path: str) -> None:
        import yaml
        with open(path, "w") as f:
            yaml.dump(self._to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @staticmethod
    def from_yaml(path: str) -> "MasterJobRepository":
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return MasterJobRepository._from_dict(data)

    def _to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @staticmethod
    def _from_dict(data: dict) -> "MasterJobRepository":
        personal = PersonalInfo(**data["personal"])
        experiences = []
        for exp_data in data.get("experiences", []):
            bullets = []
            for b in exp_data.get("bullets", []):
                variants = [CoachedVariant(**v) for v in b.get("coached_variants", [])]
                bullets.append(Bullet(
                    id=b["id"],
                    original=b["original"],
                    categories=b.get("categories", []),
                    strength_score=b.get("strength_score"),
                    coached_variants=variants,
                ))
            exp = Experience(
                company=exp_data["company"],
                title=exp_data["title"],
                start_date=exp_data["start_date"],
                end_date=exp_data.get("end_date"),
                is_current=exp_data.get("is_current", False),
                description=exp_data.get("description"),
                bullets=bullets,
            )
            experiences.append(exp)
        education = [Education(**e) for e in data.get("education", [])]
        return MasterJobRepository(
            personal=personal,
            experiences=experiences,
            skills=data.get("skills", []),
            education=education,
        )
