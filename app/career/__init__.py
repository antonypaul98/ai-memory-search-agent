"""Career Agent domain package."""

from .jobs import (
    JobImportResult,
    JobRegistry,
    JobSource,
    NormalizedJob,
    canonicalize_job_url,
)
from .matching import (
    FitScore,
    JobRequirement,
    RequirementEvidence,
    RequirementPriority,
    score_profile_fit,
)
from .models import (
    CareerFact,
    FactSensitivity,
    FactSource,
    MasterCareerProfile,
    RoleVariant,
)
from .resume import (
    ResumeChange,
    ResumeChangeKind,
    TailoredResume,
    tailor_resume,
)

__all__ = [
    "CareerFact",
    "FactSensitivity",
    "FactSource",
    "FitScore",
    "JobImportResult",
    "JobRegistry",
    "JobRequirement",
    "JobSource",
    "MasterCareerProfile",
    "NormalizedJob",
    "RequirementEvidence",
    "RequirementPriority",
    "ResumeChange",
    "ResumeChangeKind",
    "RoleVariant",
    "TailoredResume",
    "canonicalize_job_url",
    "score_profile_fit",
    "tailor_resume",
]
