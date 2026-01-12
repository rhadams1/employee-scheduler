# Ice Line Employee Scheduler

A web-based employee scheduling application for Ice Line Quad Rinks.

## Features

- **Schedule Management**: Create and manage weekly schedules (Wed-Tues)
- **Employee Management**: Add, edit, reorder, and soft-delete employees
- **Shift Templates**: Quick buttons for common shifts (Opener, Closer, etc.)
- **Auto-Save**: Changes save automatically after 1.5 seconds
- **Undo/Redo**: Full history with Ctrl+Z / Ctrl+Y
- **Excel Export**: Formatted spreadsheet with colors matching the original
- **Print/PDF**: Clean print layout for posting schedules
- **Dark Mode**: Easy on the eyes for late-night scheduling
- **Holiday Calendar**: US holidays automatically highlighted
- **Employee Notes**: Weekly notes per employee
- **Coverage View**: See staffing levels by hour
- **Keyboard Navigation**: Tab, Enter, arrow keys for fast editing

## Project Structure

```
employee-scheduler/
├── app.py                 # Flask backend (API + routes)
├── requirements.txt       # Python dependencies
├── schedule.db           # SQLite database (auto-created)
├── static/
│   ├── css/
│   │   └── main.css      # All styles including dark mode
│   ├── js/
│   │   └── main.js       # Frontend JavaScript
│   └── Ice_Line_Logo.png # Logo image
└── templates/
    └── index.html        # Main HTML template
```

## Installation

### Development

```bash
# Clone/download project
cd employee-scheduler

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py
```

Access at http://localhost:5001

### Production (Docker)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5001
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5001", "app:app"]
```

### Production (Systemd)

```ini
[Unit]
Description=Ice Line Employee Scheduler
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/employee-scheduler
Environment="PATH=/opt/employee-scheduler/venv/bin"
ExecStart=/opt/employee-scheduler/venv/bin/gunicorn -w 4 -b 127.0.0.1:5001 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/current-week` | Get current schedule week start date |
| GET | `/api/schedule/<week_start>` | Get schedule for a week |
| POST | `/api/schedule/<week_start>` | Save schedule for a week |
| POST | `/api/schedule/<week_start>/shift` | Update single shift |
| GET | `/api/schedule/<week_start>/export` | Export to Excel |
| GET | `/api/employees` | List active employees |
| POST | `/api/employees` | Add new employee |
| PUT | `/api/employees/<id>` | Update employee |
| DELETE | `/api/employees/<id>` | Soft delete employee |
| GET | `/api/notes/<week>/<emp_id>` | Get employee note |
| POST | `/api/notes/<week>/<emp_id>` | Save employee note |

## Database Schema

- **employees**: id, name, phone, section, sort_order, active
- **schedules**: id, week_start, week_title
- **shifts**: id, schedule_id, employee_id, day_index, time_in, time_out
- **office_hours**: id, schedule_id, day_index, time_in, time_out
- **events**: id, schedule_id, day_index, event_text
- **employee_notes**: id, employee_id, week_start, note

## Configuration

Environment variables:
- `SECRET_KEY`: Flask secret key (set in production!)
- `DATABASE_PATH`: Path to SQLite database (default: schedule.db)
- `FLASK_DEBUG`: Enable debug mode (default: false)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Tab | Next cell |
| Shift+Tab | Previous cell |
| Enter | Next row (same column) |
| Arrow Up/Down | Navigate rows |
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Esc | Close modal |

## License

Internal use only - Ice Line Quad Rinks
