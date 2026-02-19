# Perry Assistant Roadmap

## Vision
Perry is a personal Telegram assistant for family logistics, referee operations, and school support.
It should reduce manual coordination work and proactively surface the next important action.

## Current Baseline (Post-Refactor)
- Modular package architecture (`perry_assistant/*`) with separated bot handlers, services, integrations, and storage.
- Stable JSON persistence with bootstrap and legacy migration handling.
- Referee pipeline: Gmail parsing, assignment detection, conflict checks, calendar sync, and notifications.
- Daily schedule features: today/tomorrow/weekend summaries, morning digest, and configurable notifications.
- School absence workflows integrated into bot commands (`/absence`, `/absences`, `/excuse`).
- Safer deployment script with preflight checks, immutable image tags, remote env validation, health-check, and rollback.

## Near-Term Priorities (Next 4-8 Weeks)
1. Reliability hardening
- Job-level retry strategy for weather, Gmail, and calendar API calls.
- Error categorization and reduced noisy alerts.
- Token expiry warning before hard failure.

2. Conversation quality
- Better command hints and failure messages.
- Improve button UX for frequent actions.

3. Data quality
- Add validation for parser edge cases in referee emails.
- Add safer deduping and idempotency on repeated email scans.

4. CI checks
- Run pytest automatically on push.
- Add basic style checks for Python files.

## Mid-Term Priorities (Quarter)
1. AI parent assistant
- Natural language Q&A for calendar and game schedule.
- Daily/weekly digest summaries in conversational form.

2. Planning intelligence
- Commute-aware reminders (weather + event location + travel buffer).
- Weekly conflict forecasting across school, practice, and games.

3. Admin controls
- Structured admin command group for diagnostics, auth status, and recent failures.

## High-Value Use Cases
1. Family daily briefing
- Every morning, Perry sends one actionable schedule summary with weather and commute advice.

2. Referee operations autopilot
- New assignment emails are parsed, conflicts are detected, and calendar stays in sync with minimal manual work.

3. School absence assistant
- Parent can track, view, and mark absences as excused without leaving Telegram.

4. Parent Q&A assistant
- Parent can ask: "When is the next game?" or "What is tomorrow's plan?" and get direct answers.

5. Training load monitor
- Perry warns when short recovery windows exist between school and practice/game events.

6. Weekly planning digest
- Sunday evening summary of week schedule, potential clashes, and high-risk days.

## Reliability / DevOps Track
1. Safe one-command deploy with rollback (completed in this refactor wave).
2. Health ping and alerting for failed email/calendar/weather jobs.
3. Early warning reminders for token/auth expiration.
4. Weekly reliability report (errors, retries, uptime heuristics).

## Acceptance Milestones
### Milestone A
- Stable production behavior for all existing core commands.
- No startup path issues on Windows or Docker/Linux.

### Milestone B
- Alerting and retry policies in place.
- Referee parser accuracy improved with expanded real-email samples.

### Milestone C
- AI-assisted parent Q&A for calendar and schedule context.
