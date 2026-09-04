"""
app/models/llm_output.py
────────────────────────
Pydantic model for the structured output produced by the LLM classifier.

AGENTS.md trust boundary:
  - This model is the ONLY contract between the LLM layer and the policy engine.
  - The LLM returns JSON that must validate against LLMClassificationResult.
  - If validation fails, the policy engine treats the result as HARD_DECLINE.
  - No field in this model grants the LLM any ability to affect retry execution.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import FailureCategory


class LLMClassificationResult(BaseModel):
    """
    Structured output from the PydanticAI failure classifier.

    The policy engine reads `failure_category` and `confidence`.
    The `rationale` field is stored in the audit log for traceability only;
    it has no effect on retry decisions.
    """

    failure_category: FailureCategory = Field(
        description="The classified failure category"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Classifier confidence score between 0.0 and 1.0. "
            "Scores below 0.5 cause the policy engine to fall back to HARD_DECLINE."
        ),
    )
    rationale: str = Field(
        description=(
            "Human-readable explanation of why this category was chosen. "
            "Stored in the audit log. Has no effect on retry logic."
        )
    )
    failure_code_matched: Optional[str] = Field(
        default=None,
        description="The raw failure code the classifier received (echo-back for audit)",
    )

    @field_validator("rationale")
    @classmethod
    def rationale_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must not be blank")
        return v.strip()

    @property
    def is_confident(self) -> bool:
        """True when confidence meets the minimum threshold (0.5)."""
        return self.confidence >= 0.5

    @property
    def safe_category(self) -> FailureCategory:
        """
        Returns the classified category if confidence is sufficient,
        otherwise returns HARD_DECLINE.

        The policy engine should always use this property, never
        access `failure_category` directly.
        """
        if self.is_confident:
            return self.failure_category
        return FailureCategory.HARD_DECLINE
