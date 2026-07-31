# Kalibr Reports Bot — Production Checklist

## Secrets

- Set a unique `SECRET_KEY` and `BOOTSTRAP_KEY`.
- Add `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, and the amoCRM long-term token directly in Render.
- Do not commit `.env` or place secrets in screenshots or Telegram messages.

## amoCRM

- Create the `Employee Reports` pipeline.
- Enter pipeline and stage IDs in Render.
- Enter each manager's amoCRM user ID in the admin platform.
- Create text-compatible custom fields and save their IDs in Settings.
- Test one normal report, one actionable report, one linked customer report, and one critical report.

## Telegram and permissions

- Add branches and verify all seeded departments.
- Add managers before employees so direct-manager routing can be configured.
- Give confidential access only to explicitly approved managers and administrators.
- Generate one-time activation codes; never reuse codes.
- Confirm that each employee sees only their permitted scope.

## Reporting

- Review and edit every department's daily and weekly questions.
- Add KPI definitions and employee targets.
- Confirm schedules use `Asia/Tashkent`.
- Add approved leave and holiday exclusions before using compliance results for discipline.

## Infrastructure

- Configure S3-compatible storage before production; local worker storage is temporary.
- Enable Render health checks and external error monitoring.
- Back up PostgreSQL and test restoration.
- Verify Redis persistence is appropriate for queued jobs.

## Pilot

- Start with 5–8 employees from different departments for 3–5 working days.
- Measure AI clarification rate, correction rate, missed prompts, duplicate amoCRM records, and manager acknowledgement time.
- Fix templates and routing, then activate all 30 employees.
