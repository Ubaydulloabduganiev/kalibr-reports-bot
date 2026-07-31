# Kalibr Reports Bot

Standalone Telegram-first employee reporting system for Kalibr Books. Employees submit daily and weekly reports in Uzbek, Russian, English or mixed language. Gemini structures each report, asks for missing details, requires employee confirmation, routes it to selected managers, and sends actionable/critical records to amoCRM.

## Included

- One-time employee connection codes
- Uzbek/Russian bot and administration UI
- Text, voice, photo and document reports
- Gemini 3.1 Flash-Lite transcription, OCR/document extraction and structured JSON output
- Universal + editable department/role daily and weekly report templates
- Mandatory employee confirmation and version history
- Manager approve, return-with-reason, comment, reassign, create-task, escalate and resolve actions
- Configurable multiple departments, branches, roles, managers, recipients and visibility scopes per employee
- Daily/weekly schedules in `Asia/Tashkent`
- Reminders, overdue tracking and five-level compliance incidents
- Deterministic critical thresholds:
  - cash discrepancy: `500,000 UZS`
  - direct financial loss: `3,000,000 UZS`
  - B2B opportunity at risk: `20,000,000 UZS`
- Two-hour acknowledgement escalation for critical reports
- Daily 22:00, Saturday 23:00 weekly, and last-day 23:00 monthly executive summaries
- amoCRM API v4 leads, notes, tasks, employee-confirmed deal matching, custom fields and resolved-stage sync
- Transactional outbox, idempotency, retry/backoff and six-request-per-second limiter
- PostgreSQL, Redis, Celery worker/beat, Docker Compose and Render Blueprint

## Architecture

```text
Telegram employees/managers
        │
        ▼
aiogram bot ───────────────┐
        │                   │
        ▼                   ▼
FastAPI + PostgreSQL    Gemini API
        │
        ├── Redis/Celery schedules, retries and escalations
        ├── S3-compatible original file storage
        └── amoCRM API v4
```

Ordinary reports stay in the reporting database and manager Telegram inboxes. Only reports requiring action, high/critical risks, or explicitly linked amoCRM deals are synchronized to amoCRM.

## Local launch

1. Copy the environment file:

```bash
cp .env.example .env
```

2. Fill at least:

```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
AMOCRM_ACCESS_TOKEN=...
SECRET_KEY=use-a-long-random-value
BOOTSTRAP_KEY=use-a-separate-long-random-value
```

3. Start all services:

```bash
docker compose up --build
```

The API and bilingual admin interface will be available at:

```text
http://localhost:8000/admin
```

4. Create the first super administrator:

```bash
curl -X POST http://localhost:8000/api/v1/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "bootstrap_key": "VALUE_FROM_ENV",
    "email": "admin@kalibrbooks.uz",
    "full_name": "Kalibr Administrator",
    "password": "CHANGE_THIS_STRONG_PASSWORD",
    "language": "uz"
  }'
```

5. Log into `/admin`, create branches, then add employees. The default departments, roles, daily/weekly templates and schedules are seeded automatically. KPI definitions, employee KPI targets, report questions, risk thresholds and amoCRM mappings can be edited in the administration platform.

6. For each employee, click **Code**, then send the one-time code privately to that employee. The employee opens the Telegram bot, chooses a language and enters the code.

## amoCRM preparation

Create a private integration and configure the following Render/environment values:

```env
AMOCRM_BASE_URL=https://kalibrbooks.amocrm.ru
AMOCRM_ACCESS_TOKEN=...
AMOCRM_PIPELINE_ID=...
AMOCRM_NEW_STAGE_ID=...
AMOCRM_CRITICAL_STAGE_ID=...
AMOCRM_RESOLVED_STAGE_ID=...
```

Create an `Employee Reports` pipeline with stages such as New, Manager Review, Action Required, Waiting for Employee, Escalated, Resolved and Closed. Map each manager's amoCRM user ID in the employee form.

The current code creates leads, common notes and tasks. Custom field IDs differ per amoCRM account, so configure them in **Settings → amoCRM custom-field mapping**. Example:

```json
{
  "report_id": 123456,
  "employee": 123457,
  "department": 123458,
  "report_type": 123459,
  "report_date": 123460,
  "priority": 123461,
  "completed": 123462,
  "measurable_results": 123463,
  "blockers": 123464,
  "help_or_approval": 123465,
  "tomorrow_plan": 123466,
  "ai_confidence": 123467,
  "confidential": 123468
}
```

The mapped amoCRM fields should accept text values. Reports that mention a customer or telephone number show candidate deals to the employee; no deal is linked until the employee confirms it.

## Render deployment

1. Push this repository to a private GitHub repository.
2. In Render, create a Blueprint from `render.yaml`.
3. Fill all `sync: false` secrets.
4. Run the `kalibr-reports-seed` job once after the database migration.
5. Create the first administrator using the public API URL and the generated `BOOTSTRAP_KEY`.
6. Set `APP_BASE_URL` and enable secure cookies after the production URL is known.

Render services:

- `kalibr-reports-api`
- `kalibr-reports-bot`
- `kalibr-reports-worker`
- `kalibr-reports-beat`
- `kalibr-reports-redis`
- `kalibr-reports-db`

## Tests and checks

```bash
pytest -q
ruff check app tests
python -m compileall -q app
```

## Production hardening still required before all 30 employees launch

- Configure S3-compatible object storage; Render local disk is not permanent.
- Add amoCRM custom-field IDs and verify pipeline/stage IDs.
- Connect approved-leave/calendar data to exclude authorized absences from compliance.
- Load the official Uzbekistan holiday calendar before company-wide enforcement.
- Add encrypted secret management if integration credentials later move into the database.
- Add Sentry/monitoring DSN and production alert destination.
- Run a pilot with 5–8 users for 3–5 days, then activate all departments.

## Important security rules

- Never commit `.env`.
- Never send Telegram, Gemini or amoCRM tokens in chat or screenshots.
- Use a private GitHub repository.
- Give confidential-report permissions only to explicitly approved users.
- Rotate the amoCRM token and all secrets after any suspected exposure.
