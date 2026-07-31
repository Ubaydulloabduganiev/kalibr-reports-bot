from __future__ import annotations

import asyncio
from pathlib import Path

from google import genai

from app.core.config import settings
from app.schemas import StructuredReport

UNIVERSAL_QUESTIONS = [
    "What was completed today?",
    "What measurable result was achieved?",
    "What remains unfinished?",
    "What problems or blockers appeared?",
    "Is help or approval required?",
    "What is planned for tomorrow?",
    "Is anything urgent?",
]

WEEKLY_QUESTIONS = [
    "What were the main achievements this week?",
    "What KPI result was achieved compared with the target?",
    "What important work remains unfinished?",
    "Which blockers repeated during the week?",
    "What risks may affect next week?",
    "What support or approvals are required?",
    "What are the priorities for next week?",
]


class GeminiService:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    def _require_client(self) -> genai.Client:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return self.client

    async def transcribe_audio(self, path: Path, language_hint: str = "auto") -> str:
        client = self._require_client()

        def _transcribe() -> str:
            uploaded = client.files.upload(file=str(path))
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        (
                            "Transcribe this employee voice report accurately. Preserve names, numbers, dates, "
                            f"amounts and mixed Uzbek/Russian/English wording. Language hint: {language_hint}. "
                            "Return only the transcript."
                        ),
                        uploaded,
                    ],
                )
                return response.text.strip()
            finally:
                if getattr(uploaded, "name", None):
                    try:
                        client.files.delete(name=uploaded.name)
                    except Exception:
                        pass

        return await asyncio.to_thread(_transcribe)

    async def extract_file_text(self, path: Path, mime_type: str | None = None) -> str:
        client = self._require_client()

        def _extract_file() -> str:
            uploaded = client.files.upload(file=str(path))
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        (
                            "Extract all report-relevant content from this employee attachment. "
                            "For images, perform accurate OCR. For PDFs/documents, preserve names, numbers, "
                            "dates, tables and monetary amounts. Do not invent content. Return plain text only."
                        ),
                        uploaded,
                    ],
                )
                return response.text.strip()
            finally:
                if getattr(uploaded, "name", None):
                    try:
                        client.files.delete(name=uploaded.name)
                    except Exception:
                        pass

        return await asyncio.to_thread(_extract_file)

    async def extract_report(
        self,
        *,
        original_text: str,
        employee_context: str,
        role_questions: list[str] | None = None,
        report_type: str = "daily",
        prior_structured: StructuredReport | None = None,
        correction: str | None = None,
    ) -> StructuredReport:
        client = self._require_client()
        base_questions = WEEKLY_QUESTIONS if report_type == "weekly" else UNIVERSAL_QUESTIONS
        questions = base_questions + (role_questions or [])
        correction_context = ""
        if prior_structured and correction:
            correction_context = (
                "\nPrevious structured report:\n"
                f"{prior_structured.model_dump_json(indent=2)}\n"
                f"Employee correction:\n{correction}\n"
                "Apply the correction and regenerate the complete report."
            )

        prompt = f"""
You structure internal employee reports for Kalibr Books.
Employee context: {employee_context}
Expected questions: {questions}

Rules:
- Extract facts only. Never invent KPI values, money, customers, deadlines or risks.
- Preserve all measurable numbers and use UZS for money values explicitly stated in UZS.
- If a required fact is missing or ambiguous, add a concise clarification question.
- Identify critical risk categories conservatively; deterministic business rules will validate them later.
- Mark confidential when the content concerns HR, salaries, misconduct, fraud, cash, legal/copyright, data security, or sensitive finance.
- Confidence is 0..1 and must reflect extraction certainty.
- The employee may mix Uzbek Latin, Uzbek Cyrillic, Russian and English.

Employee report:
{original_text}
{correction_context}
""".strip()

        def _extract() -> StructuredReport:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": StructuredReport.model_json_schema(),
                    "temperature": 0.1,
                },
            )
            return StructuredReport.model_validate_json(response.text)

        return await asyncio.to_thread(_extract)


gemini_service = GeminiService()
