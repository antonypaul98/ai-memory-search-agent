"""Chat request and response models."""

from pydantic import BaseModel, Field, model_validator

from app.models.consensus import ConsensusReport
from app.models.reflection import RecommendationItem
from app.models.metrics import SearchMetrics
from app.models.verification import VerificationReport


class ChatRequest(BaseModel):
    """Grounded chat request."""

    question: str = Field(min_length=1, description="Question to answer from saved memories.")
    top_k: int = Field(default=6, ge=1, le=10, description="Number of chunks to retrieve.")
    clarification_choice: str | None = Field(
        default=None,
        description="Selected clarifying option when the question is ambiguous.",
    )
    debug: bool = Field(default=False, description="Include debug metrics when app debug mode is enabled.")

    @model_validator(mode="after")
    def validate_question(self) -> "ChatRequest":
        stripped = self.question.strip()
        if not stripped:
            raise ValueError("Question cannot be empty.")
        self.question = stripped
        return self


class ClarificationOption(BaseModel):
    id: str
    label: str


class ChatSource(BaseModel):
    """One cited memory chunk supporting the answer."""

    video_id: str
    title: str
    url: str
    start_time: float | None = None
    end_time: float | None = None
    matched_text: str
    relevance_score: float
    timestamp_url: str


class ChatResponse(BaseModel):
    """Grounded chat response with citations and knowledge-engine analysis."""

    answer: str
    sources: list[ChatSource]
    grounded: bool
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    clarification_options: list[ClarificationOption] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    confidence: str | None = None
    verification: VerificationReport | None = None
    consensus: ConsensusReport | None = None
    debug_metrics: SearchMetrics | None = None
