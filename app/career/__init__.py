"""Career Agent domain package."""

from .application_answers import (
    AnswerStatus,
    ApplicationQuestion,
    GeneratedApplicationAnswer,
    generate_application_answer,
    generate_application_answers,
)
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
    "AnswerStatus",
    "ApplicationQuestion",
    "CareerFact",
    "FactSensitivity",
    "FactSource",
    "FitScore",
    "GeneratedApplicationAnswer",
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
    "generate_application_answer",
    "generate_application_answers",
    "score_profile_fit",
    "tailor_resume",
]
