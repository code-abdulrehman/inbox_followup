# Dev Notes — UI Refactoring & Real-Time Logs

## What Changed
- **Theme system** — CSS custom properties on `:root` + `[data-theme="dark"]` selectors, light/dark mode toggle in navbar (persisted to localStorage via `theme.js`)
- **Reusable partials** — `navbar.html`, `stat_card.html`, `run_logs_panel.html` in `templates/partials/`
- **Toast notifications** — `toast.js` provides `showToast(message, type, duration)` called by all templates
- **Real-time run logs (SSE)** — manual report runs now execute in a background thread; the `run_logger.py` service buffers events; the SSE endpoint `/api/reports/run-now/events/{run_id}` streams them; frontend uses `EventSource` in `run-report.js`
- **Dashboard chart** — simple bar chart showing emails checked per day for last 7 reports
- **Settings tabs** — settings page grouped into 4 tabs: Connection, Reports, AI & Features, Notifications
- **Reports search/filter** — client-side text search and status dropdown filter on the reports table
- **HTML report viewer** — `/reports/{id}/html` endpoint renders the raw HTML report standalone
- **Scheduler test endpoint** — `GET /api/scheduler/test` triggers the scheduled job manually
- **Force re-run button** — "Force Re-run" button on dashboard bypasses duplicate report check

## Files Created
- `app/services/run_logger.py` — SSE event buffer with thread safety
- `app/static/css/global.css` — complete theme system
- `app/static/js/theme.js` — theme toggle with localStorage
- `app/static/js/toast.js` — toast notification system
- `app/static/js/run-report.js` — SSE client for live run logs
- `app/templates/partials/navbar.html`
- `app/templates/partials/stat_card.html`
- `app/templates/partials/run_logs_panel.html`
- `DEV_NOTES.md`

## Files Modified
- `app/main.py` — no structural changes needed (existing static mount covers js/css dirs)
- `app/routes/ui.py` — added `recent_reports` + `max_emails` to dashboard context, added `/reports/{id}/html` route
- `app/routes/api.py` — refactored `run_report_now` to use background thread + SSE; added SSE events endpoint; added `/scheduler/test`
- `app/services/report_service.py` — added `run_id` parameter, integrated `run_logger.add_log()` at each step
- `app/services/scheduler_service.py` — added `run_scheduled_job(db, settings)` helper for test endpoint
- `app/templates/base.html` — includes new CSS/JS, navbar partial
- `app/templates/dashboard.html` — cleaner cards, chart, run logs panel, force re-run button
- `app/templates/settings.html` — tabbed layout, grouped sections
- `app/templates/reports.html` — search/filter, run logs panel
- `app/templates/report_detail.html` — cleaner layout, HTML report link
- `README.md` — updated structure, endpoints, test checklist

## How to Verify
1. Start the app: `python run.py`
2. Open http://localhost:8000
3. Toggle dark mode (🌙/☀️ button in navbar) — should persist on reload
4. Click "Run Manual Report" — should show live logs streaming in dashboard
5. Go to Settings — tabs should switch between sections
6. Go to Reports — search field filters rows, status dropdown works
7. Open a report detail — HTML preview renders, "Open Full" link works
8. Visit `/api/scheduler/test` — should execute scheduled report
9. Check for toast notifications on success/error

## Known Issues
- Two identical `#run-logs-panel` divs appear on dashboard (one in "Last Report" section, one in "Quick Actions"); JS deduplication hides the second
- If server is restarted, in-memory SSE buffers are lost (acceptable for MVP)
- Background thread uses `SessionLocal()` directly — ensure `SessionLocal` is importable at module level (it is, from `app.database`)
