# Inbox FollowUp

AI-powered email automation dashboard. Connects to Gmail, reads daily emails, analyzes them with AI (NVIDIA/OpenRouter), generates smart daily summaries, and sends clean report emails via Resend.

## Features

- **Gmail Integration** — OAuth 2.0 readonly access, fetches emails based on filter rules
- **AI Analysis** — Categorizes emails, detects priority, meetings, deadlines, and suggests replies
- **Dual AI Providers** — NVIDIA AI primary, OpenRouter fallback, rule-based fallback as last resort
- **Daily Reports** — Auto-generated executive summaries with priority sections
- **Email Delivery** — Sends polished HTML reports via Resend API
- **APScheduler** — Configurable daily automation with timezone support
- **Manual Run** — One-click report generation from the dashboard
- **Job Locking** — Prevents duplicate runs and loops
- **Admin Dashboard** — Clean web UI for settings, reports, and monitoring

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, APScheduler
- **Database:** PostgreSQL
- **Frontend:** Server-rendered HTML, CSS, vanilla JavaScript
- **APIs:** Gmail API (readonly), NVIDIA AI, OpenRouter, Resend
- **Auth:** Google OAuth 2.0

## Project Structure

```
inbox_follow_up/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py             # Environment config
│   ├── database.py           # SQLAlchemy engine/session
│   ├── models.py             # Database models
│   ├── routes/
│   │   ├── ui.py             # Dashboard, settings, reports pages
│   │   ├── api.py            # REST API endpoints
│   │   └── gmail_auth.py     # Gmail OAuth flow
│   ├── services/
│   │   ├── gmail_service.py  # Gmail API operations
│   │   ├── ai_service.py     # AI analysis (NVIDIA/OpenRouter/rule-based)
│   │   ├── report_service.py # Report generation and orchestration
│   │   ├── email_service.py  # Resend email sending
│   │   └── scheduler_service.py  # APScheduler management
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS styles
├── .env.example
├── requirements.txt
├── create_tables.py
├── run.py
└── README.md
```

## Prerequisites

- Python 3.10+
- PostgreSQL database
- Google Cloud project with Gmail API enabled
- NVIDIA API key (or OpenRouter API key)
- Resend API key and verified domain/email

## Setup

### 1. Clone and Install Dependencies

```bash
cd inbox_follow_up
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create PostgreSQL Database

```sql
CREATE DATABASE inbox_followup;
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Must match your Google Cloud Console setting |
| `NVIDIA_API_KEY` | NVIDIA AI API key |
| `NVIDIA_MODEL` | NVIDIA model name (default: meta/llama-3.1-405b-instruct) |
| `OPENROUTER_API_KEY` | (Optional) OpenRouter fallback API key |
| `RESEND_API_KEY` | Resend API key for sending report emails |
| `RESEND_FROM_EMAIL` | Verified sender email in Resend |
| `APP_SECRET_KEY` | Random secret key for sessions |
| `APP_BASE_URL` | Your app URL (default: http://localhost:8000) |

### 4. Create Database Tables

```bash
python create_tables.py
```

### 5. Run the Application

```bash
python run.py
```

Open http://localhost:8000 in your browser.

## Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable **Gmail API**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Add redirect URI: `http://localhost:8000/api/gmail/callback`
7. Copy Client ID and Client Secret to `.env`
8. In OAuth consent screen, add `http://localhost:8000` to authorized domains (testing mode)
9. Add the `.../auth/gmail.readonly` scope

## How It Works

### Email Fetching

On each report run, the app queries Gmail using the configured filter type:

- `today_all` — all emails from today
- `today_unread` — unread emails from today
- `today_read` — read emails from today
- `important` — important emails from today
- `starred` — starred emails from today
- `custom_query` — your own Gmail search query

### AI Analysis

Each email is sent to the configured AI provider for analysis:
1. **NVIDIA AI** (primary) — uses NVIDIA NIM API
2. **OpenRouter** (fallback) — if NVIDIA fails
3. **Rule-based** (last resort) — keyword matching if all AI providers fail

The AI returns: category, priority, priority score, needs_reply, meeting_detected, deadline_detected, summary, suggested reply, and action items.

### Report Generation

The app generates three formats:
- **Markdown** — plain text summary
- **HTML** — styled report with cards, tables, and badges
- **JSON** — structured data for API consumption

### Scheduler

APScheduler runs the report job daily at your configured time. The scheduler auto-starts with the app and auto-updates when settings change.

### Job Locking

- Only one report job runs at a time
- Locks auto-release after 30 minutes (stale lock protection)
- Duplicate reports for the same date are prevented
- Manual runs can use `force=true` to bypass duplicate check

## How to Run a Manual Report

1. Open the Dashboard
2. Click **"Run Manual Report"**
3. Wait for the report to generate
4. View the report in the Reports list

Or via API:

```bash
curl -X POST http://localhost:8000/api/reports/run-now
```

Force run (bypasses duplicate check):

```bash
curl -X POST "http://localhost:8000/api/reports/run-now?force=true"
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Dashboard UI |
| GET | `/settings` | Settings UI |
| GET | `/reports` | Reports list UI |
| GET | `/reports/{id}` | Report detail UI |
| GET | `/api/status` | API status overview |
| GET | `/api/settings` | Get app settings |
| POST | `/api/settings` | Update app settings |
| GET | `/api/gmail/connect` | Start Gmail OAuth flow |
| GET | `/api/gmail/callback` | Gmail OAuth callback |
| GET | `/api/gmail/status` | Check Gmail connection |
| POST | `/api/gmail/disconnect` | Disconnect Gmail |
| POST | `/api/reports/run-now` | Trigger manual report |
| GET | `/api/reports` | List all reports |
| GET | `/api/reports/{id}` | Get report details |

## Safety & Privacy

- **Readonly Gmail scope** — the app never modifies, sends, or deletes emails
- **Body preview limit** — email bodies are truncated to 1200 characters before AI processing
- **No token logging** — OAuth tokens are never written to logs
- **.env is gitignored** — secrets are never committed
- **Report self-exclusion** — the app's own report emails are excluded from fetching
- **This is a local MVP/demo** — not production-ready
- **Production should encrypt OAuth tokens** at rest

## Test Checklist

- [ ] App starts successfully
- [ ] Dashboard loads with default settings
- [ ] Settings page loads and saves correctly
- [ ] Gmail OAuth flow connects successfully
- [ ] Gmail fetch returns emails based on filter
- [ ] AI analysis completes (with or without API keys)
- [ ] Report generates with correct sections
- [ ] Report HTML preview renders correctly
- [ ] Resend sends report email
- [ ] Manual run button works
- [ ] Scheduler triggers at configured time
- [ ] Duplicate prevention works
- [ ] Error states are handled gracefully

## Known Limitations

- Single admin user only (no multi-user auth)
- OAuth tokens stored in plain text (encrypt in production)
- No pagination for very large email volumes
- No email reply/send capability (readonly by design)
- Basic rule-based analysis when AI APIs are unavailable

## Future Improvements

- Multi-user support with authentication
- Encrypted OAuth token storage
- Pagination for large inboxes
- Custom AI prompt templates
- Email reply suggestions (click to respond)
- Slack/Telegram/Discord notification channels
- Historical trends and analytics charts
- Export reports to PDF

---

Built with Python, FastAPI, and AI. For demo and learning purposes.
