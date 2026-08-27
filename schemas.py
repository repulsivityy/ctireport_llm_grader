from typing import List, Optional
from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    score: int = Field(
        ...,
        ge=0,
        le=25,
        description="Score from 0 to 25 based on rubric calibrated to the report type."
    )
    explanation: str = Field(
        ...,
        description="Clear explanation justifying the score based on the criteria."
    )


class GradingResult(BaseModel):
    student_name: str = Field(
        ...,
        description="Name of the student."
    )
    student_email: Optional[str] = Field(
        default=None,
        description="Authenticated Google email of the student."
    )
    report_title: str = Field(
        default="Threat Intelligence Report",
        description="Title or primary subject of the threat intelligence report."
    )
    report_type: str = Field(
        default="Country Threat Landscape",
        description="Type of CTI report: 'Threat Actor Deep Dive Report', 'Country Threat Landscape', or 'CVE Strategic Reporting'."
    )
    actionability: CriterionScore = Field(
        ...,
        description="Actionability (0-25): Can stakeholders/security teams take direct action based on the report type?"
    )
    clarity_of_scope: CriterionScore = Field(
        ...,
        description="Clarity of Scope (0-25): Are target sectors, countries/regions, or systems clearly defined?"
    )
    evidence_and_attribution: CriterionScore = Field(
        ...,
        description="Evidence and Attribution (0-25): Are claims backed by solid data/telemetry calibrated to report type?"
    )
    methodology: CriterionScore = Field(
        ...,
        description="Methodology (0-25): Does the report explain how intelligence was gathered and analyzed?"
    )
    total_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Sum of the 4 category scores (0 to 100 scale)."
    )
    percentage_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage score (0-100%)."
    )
    letter_grade: str = Field(
        ...,
        description="Letter grade (A, B, C, D, F) based on performance."
    )
    gaps_and_logical_fallacies: List[str] = Field(
        default_factory=list,
        description="List of specific gaps, logical fallacies, or missing context in the report."
    )
    questions_for_author: List[str] = Field(
        default_factory=list,
        description="Exactly three probing questions to ask the report's author to clarify or validate their findings."
    )
    overall_critique: str = Field(
        ...,
        description="Senior analyst overall critique and evaluation summary."
    )


class MultiStageGradingResult(BaseModel):
    level_1_result: Optional[GradingResult] = None
    final_result: GradingResult
    primary_model_used: str = "gemini-3.5-flash-lite"
    final_model_used: str = "gemini-3.7-flash"


class SubmissionRecord(BaseModel):
    submission_id: str
    timestamp: str
    student_name: str
    student_email: str
    attempt_number: int
    report_title: str
    report_type: str
    filename: Optional[str] = None
    file_type: str
    report_content: str = Field(
        ...,
        description="Complete raw/sanitized text content of the uploaded report."
    )
    total_score: int
    percentage_score: float
    letter_grade: str
    actionability_score: int
    clarity_of_scope_score: int
    evidence_and_attribution_score: int
    methodology_score: int
    primary_model_used: str
    final_model_used: str
    level_1_result: Optional[GradingResult] = None
    result: GradingResult
