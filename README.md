# Ice Line Employee Scheduler

A Flask-based employee scheduling application for Ice Line Quad Rinks.

## Features

- **Visual weekly schedule** with color-coded sections (managers, Zak, staff)
- **Click-to-edit shifts** with time picker modal
- **Manager/Employee view toggle** (employees see read-only, no hours)
- **Week navigation** - move between weeks
- **Copy previous week** - use last week as template
- **Hours calculation** with overtime warnings (40+ hours)
- **Office hours editing** - click to modify open/close times
- **Event management** - add special events per day
- **Employee management** - add/edit/remove staff
- **Coverage view** - see staffing levels by hour
- **Excel export** - full formatting with colors matching original format
- **Print-friendly** - clean output for printing

## Requirements

- Python 3.8+
- Flask
- openpyxl

## Installation

```bash
# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install flask openpyxl

# Run the app
python app.py
```

The app will start at http://localhost:5001

## Project Structure

```
employee-scheduler/
├── app.py              # Flask backend with API endpoints
├── schedule.db         # SQLite database (created automatically)
├── templates/
│   └── index.html      # Frontend application
└── README.md
```

## API Endpoints

### Schedules
- `GET /api/schedule/<week_start>` - Get schedule for a week (week_start is Monday in YYYY-MM-DD format)
- `POST /api/schedule/<week_start>` - Save entire schedule
- `POST /api/schedule/<week_start>/shift` - Update a single shift
- `GET /api/schedule/<week_start>/export` - Download Excel file

### Employees
- `GET /api/employees` - List all active employees
- `POST /api/employees` - Add new employee
- `PUT /api/employees/<id>` - Update employee
- `DELETE /api/employees/<id>` - Soft delete employee

## Database

SQLite database with tables:
- `employees` - Staff members with name, phone, section (manager/zak/staff)
- `schedules` - Weekly schedules indexed by week_start date
- `shifts` - Individual shifts linked to schedule and employee
- `office_hours` - Daily office open/close times
- `events` - Special events per day

## Deployment

For production deployment on your Proxmox server:

1. Copy files to your server
2. Install dependencies in a virtual environment
3. Use gunicorn or similar WSGI server:
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5001 app:app
   ```
4. Set up as a systemd service or run in an LXC container
5. Configure reverse proxy (nginx/Caddy) if needed

## Future Enhancements (Phase 5+)

- Employee login portal
- Time-off request submission
- Availability/school schedule input
- Shift swap requests
- Email notifications
- Multi-location support
