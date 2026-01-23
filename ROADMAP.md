# Ice Line Employee Scheduler - Roadmap

## Current Status (January 2026)

The scheduler is **feature-complete for basic use** with a solid foundation:

- Weekly scheduling (Wed-Tue) with shift templates
- Three employee sections: Managers, Zak, Staff
- Auto-save, undo/redo, dark mode, keyboard navigation
- Excel export with color coding
- Employee portal (read-only mobile view at `/employee`)
- Backup/restore system
- Production deployment on Cloudflare/Nginx

---

## Phase 1: Security Hardening (Critical)

The app currently has **no authentication**. Anyone with the URL can view and modify schedules.

### 1.1 Basic Authentication
- [ ] Add Flask-Login for session management
- [ ] Create admin login page (username/password)
- [ ] Protect all `/api/*` endpoints except read-only employee portal
- [ ] Add logout functionality
- [ ] Store passwords with bcrypt hashing

### 1.2 CSRF Protection
- [ ] Add Flask-WTF for CSRF tokens
- [ ] Include CSRF token in all form submissions
- [ ] Validate tokens on POST/PUT/DELETE requests

### 1.3 Rate Limiting
- [ ] Add Flask-Limiter
- [ ] Limit login attempts (5/minute)
- [ ] Limit API calls (100/minute per IP)

### 1.4 Input Validation
- [ ] Validate time formats on server side
- [ ] Sanitize employee notes (prevent XSS)
- [ ] Validate week_start date formats

---

## Phase 2: Data Integrity

### 2.1 Shift Conflict Detection
- [ ] Warn when employee has overlapping shifts
- [ ] Prevent double-booking same employee same time slot
- [ ] Visual indicator for conflicts in UI

### 2.2 Audit Log
- [ ] Create `audit_log` table (who, what, when, old_value, new_value)
- [ ] Log all schedule changes
- [ ] Log employee additions/deletions
- [ ] Add admin view to browse audit history

### 2.3 Data Validation
- [ ] Enforce max hours per week (configurable, e.g., 50)
- [ ] Validate shift durations (min 1 hour, max 16 hours)
- [ ] Require at least one manager per day

---

## Phase 3: Notifications

### 3.1 Email Notifications
- [ ] Add email configuration (SMTP or SendGrid)
- [ ] Email employees when their schedule changes
- [ ] Weekly schedule summary email (opt-in)
- [ ] Email admin on backup failures

### 3.2 SMS Notifications (Optional)
- [ ] Twilio integration for SMS
- [ ] Text employees for same-day schedule changes
- [ ] Shift reminder texts (morning of)

---

## Phase 4: Reporting & Analytics

### 4.1 Hours Reports
- [ ] Weekly hours per employee report
- [ ] Monthly hours summary
- [ ] Overtime tracking (>40 hrs/week)
- [ ] Export reports to Excel

### 4.2 Coverage Analysis
- [ ] Identify understaffed time slots
- [ ] Historical coverage trends
- [ ] Peak hours analysis

### 4.3 Employee Metrics
- [ ] Days worked per month
- [ ] Schedule consistency score
- [ ] No-show tracking (future)

---

## Phase 5: Developer Experience

### 5.1 Testing
- [ ] Set up pytest
- [ ] Unit tests for API endpoints
- [ ] Integration tests for schedule operations
- [ ] Test coverage reporting

### 5.2 CI/CD
- [ ] GitHub Actions workflow
- [ ] Lint on PR (flake8, eslint)
- [ ] Run tests on PR
- [ ] Auto-deploy to staging on merge

### 5.3 Code Quality
- [ ] Add Python type hints
- [ ] Add JSDoc comments to main.js
- [ ] Split main.js into modules (ES6 imports)
- [ ] Add error tracking (Sentry)

---

## Phase 6: Enhanced Features (Nice to Have)

### 6.1 Availability Management
- [ ] Employees submit availability preferences
- [ ] Time-off requests with approval workflow
- [ ] Recurring unavailability (e.g., "never Sundays")

### 6.2 Shift Swapping
- [ ] Employee-initiated shift swap requests
- [ ] Manager approval for swaps
- [ ] Notifications for swap requests

### 6.3 Templates & Patterns
- [ ] Save schedule templates
- [ ] Apply template to new week
- [ ] Rotating schedule patterns

### 6.4 Mobile App / PWA
- [ ] Service worker for offline access
- [ ] Push notifications
- [ ] Add to home screen prompt

---

## Tech Debt

- [ ] Remove hardcoded default employees from `init_db()`
- [ ] Move SECRET_KEY to required env var (no fallback)
- [ ] Add health check endpoint (`/health`)
- [ ] Database migrations system (Alembic)
- [ ] Consolidate CSS variables between main.css and employee_portal.css

---

## File Structure Reference

```
employee-scheduler/
├── app.py                 # Flask backend (main application)
├── requirements.txt       # Python dependencies
├── schedule.db           # SQLite database (gitignored)
├── static/
│   ├── css/
│   │   ├── main.css              # Admin styles
│   │   └── employee_portal.css   # Employee portal styles
│   ├── js/
│   │   ├── main.js               # Admin logic (~1,800 lines)
│   │   └── employee_portal.js    # Portal logic (~340 lines)
│   └── Ice_Line_Logo.png
├── templates/
│   ├── index.html               # Admin interface
│   └── employee_portal.html     # Employee portal
├── ROADMAP.md            # This file
├── IMPROVEMENTS.md       # Additional improvement notes
└── DEPLOYMENT.md         # Production deployment guide
```

---

## Quick Reference

| URL | Purpose |
|-----|---------|
| `/` | Admin scheduler (full access) |
| `/employee` | Employee portal (read-only) |
| `/api/backup/export` | Download database backup |

---

*Last updated: January 2026*
