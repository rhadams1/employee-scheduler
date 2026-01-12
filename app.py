"""
Ice Line Employee Scheduler - Flask Backend
Production-ready version with proper error handling and configuration
"""

import os
import logging
from datetime import datetime, timedelta, date
from io import BytesIO
from functools import wraps

from flask import Flask, jsonify, request, send_file, render_template, g
import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Application configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DATABASE = os.environ.get('DATABASE_PATH', 'schedule.db')
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    # Schedule configuration
    WEEK_START_DAY = 'wednesday'  # Schedule week starts on Wednesday
    DEFAULT_OFFICE_OPEN = '8:00 AM'
    DEFAULT_OFFICE_CLOSE = '10:00 PM'
    
    # Default employees (only used on first run)
    DEFAULT_EMPLOYEES = [
        ('Bob Adams', '610-505-6322', 'manager', 1),
        ('Dave Hendricks', '484-459-8620', 'manager', 2),
        ('Zak Reilly', '267-247-2955', 'zak', 1),
        ('Ava Hawthorne', '(267) 738-4698', 'staff', 1),
        ('Marisa Fullerton', '(215) 252-6544', 'staff', 2),
        ('Nate Bailey', '(609) 832-9499', 'staff', 3),
        ('Lilli Binns', '', 'staff', 4),
        ('Olivia Binns', '', 'staff', 5),
        ('Hunter Haas', '(484) 631-5469', 'staff', 6),
        ('Lena Sturz', '', 'staff', 7),
    ]


# =============================================================================
# APPLICATION FACTORY
# =============================================================================

def create_app(config_class=Config):
    """Application factory pattern"""
    app = Flask(__name__, 
                static_folder='static', 
                template_folder='templates')
    
    app.config.from_object(config_class)
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if app.config['DEBUG'] else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Register blueprints/routes
    register_routes(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Setup database
    with app.app_context():
        init_db()
    
    return app


# =============================================================================
# DATABASE
# =============================================================================

def get_db():
    """Get database connection for current request"""
    if 'db' not in g:
        g.db = sqlite3.connect(Config.DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Close database connection"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database schema and default data"""
    conn = sqlite3.connect(Config.DATABASE)
    cursor = conn.cursor()
    
    # Create tables
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            section TEXT NOT NULL CHECK(section IN ('manager', 'zak', 'staff')),
            sort_order INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start DATE NOT NULL UNIQUE,
            week_title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL CHECK(day_index >= 0 AND day_index <= 6),
            time_in TEXT,
            time_out TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            UNIQUE(schedule_id, employee_id, day_index)
        );
        
        CREATE TABLE IF NOT EXISTS office_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL CHECK(day_index >= 0 AND day_index <= 6),
            time_in TEXT,
            time_out TEXT,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
            UNIQUE(schedule_id, day_index)
        );
        
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL CHECK(day_index >= 0 AND day_index <= 6),
            event_text TEXT NOT NULL,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS employee_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            week_start DATE NOT NULL,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            UNIQUE(employee_id, week_start)
        );
        
        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_shifts_schedule ON shifts(schedule_id);
        CREATE INDEX IF NOT EXISTS idx_shifts_employee ON shifts(employee_id);
        CREATE INDEX IF NOT EXISTS idx_schedules_week ON schedules(week_start);
        CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(active, section);
    ''')
    
    # Seed default employees if table is empty
    cursor.execute('SELECT COUNT(*) FROM employees')
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            'INSERT INTO employees (name, phone, section, sort_order) VALUES (?, ?, ?, ?)',
            Config.DEFAULT_EMPLOYEES
        )
        logging.info("Initialized default employees")
    
    conn.commit()
    conn.close()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_week_dates(week_start_str):
    """Generate day info for the week starting from Wednesday"""
    week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
    day_names = ['Wed', 'Thurs', 'Fri', 'Sat', 'Sun', 'Mon', 'Tues']
    wed = week_start + timedelta(days=2)  # Monday + 2 = Wednesday
    
    return [
        {
            'name': name,
            'date': f"{(wed + timedelta(days=i)).month}/{(wed + timedelta(days=i)).day}",
            'fullDate': (wed + timedelta(days=i)).isoformat(),
            'isWeekend': name in ['Sat', 'Sun']
        }
        for i, name in enumerate(day_names)
    ]


def format_week_title(wed_date):
    """Format week title like 'December 31st, 2025'"""
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    
    day = wed_date.day
    if day in [1, 21, 31]:
        suffix = 'st'
    elif day in [2, 22]:
        suffix = 'nd'
    elif day in [3, 23]:
        suffix = 'rd'
    else:
        suffix = 'th'
    
    return f"{months[wed_date.month - 1]} {day}{suffix}, {wed_date.year}"


def get_current_week_start():
    """Calculate the Monday of the current schedule week"""
    today = date.today()
    weekday = today.weekday()  # 0=Mon, 1=Tue, 2=Wed, etc.
    
    # Schedule runs Wed-Tues
    # If Mon(0) or Tue(1), we're still in the previous week's schedule
    if weekday < 2:
        days_back = 7 + weekday
    else:
        days_back = weekday
    
    monday = today - timedelta(days=days_back)
    return monday.isoformat()


def get_or_create_schedule(week_start_str):
    """Get existing schedule or create new one"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT * FROM schedules WHERE week_start = ?', (week_start_str,))
    schedule = cursor.fetchone()
    
    if not schedule:
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        wed = week_start + timedelta(days=2)
        week_title = format_week_title(wed)
        
        cursor.execute(
            'INSERT INTO schedules (week_start, week_title) VALUES (?, ?)',
            (week_start_str, week_title)
        )
        schedule_id = cursor.lastrowid
        
        # Create default office hours
        for i in range(7):
            cursor.execute(
                'INSERT INTO office_hours (schedule_id, day_index, time_in, time_out) VALUES (?, ?, ?, ?)',
                (schedule_id, i, Config.DEFAULT_OFFICE_OPEN, Config.DEFAULT_OFFICE_CLOSE)
            )
        
        db.commit()
        cursor.execute('SELECT * FROM schedules WHERE id = ?', (schedule_id,))
        schedule = cursor.fetchone()
    
    return dict(schedule)


def build_schedule_response(week_start_str):
    """Build complete schedule data for API response"""
    db = get_db()
    cursor = db.cursor()
    
    schedule = get_or_create_schedule(week_start_str)
    schedule_id = schedule['id']
    
    # Get active employees ordered by section and sort_order
    cursor.execute('''
        SELECT * FROM employees 
        WHERE active = 1 
        ORDER BY 
            CASE section WHEN 'manager' THEN 1 WHEN 'zak' THEN 2 WHEN 'staff' THEN 3 END,
            sort_order
    ''')
    employees = [dict(row) for row in cursor.fetchall()]
    
    # Get shifts as lookup dictionary
    cursor.execute('SELECT * FROM shifts WHERE schedule_id = ?', (schedule_id,))
    shifts = {
        (row['employee_id'], row['day_index']): {'in': row['time_in'], 'out': row['time_out']}
        for row in cursor.fetchall()
    }
    
    # Get office hours
    cursor.execute('SELECT * FROM office_hours WHERE schedule_id = ? ORDER BY day_index', (schedule_id,))
    oh_dict = {row['day_index']: row for row in cursor.fetchall()}
    office_hours = [
        {'in': oh_dict[i]['time_in'], 'out': oh_dict[i]['time_out']} if i in oh_dict
        else {'in': Config.DEFAULT_OFFICE_OPEN, 'out': Config.DEFAULT_OFFICE_CLOSE}
        for i in range(7)
    ]
    
    # Get events grouped by day
    cursor.execute('SELECT * FROM events WHERE schedule_id = ?', (schedule_id,))
    events_by_day = {i: [] for i in range(7)}
    for row in cursor.fetchall():
        if row['event_text']:
            events_by_day[row['day_index']].append(row['event_text'])
    
    # Get employee notes for this week
    cursor.execute(
        'SELECT employee_id, note FROM employee_notes WHERE week_start = ?',
        (week_start_str,)
    )
    notes = {row['employee_id']: row['note'] for row in cursor.fetchall()}
    
    # Build employee data with shifts
    def build_employee(emp):
        return {
            'id': emp['id'],
            'name': emp['name'],
            'phone': emp['phone'] or '',
            'shifts': [shifts.get((emp['id'], i)) for i in range(7)],
            'note': notes.get(emp['id'], '')
        }
    
    managers = [build_employee(e) for e in employees if e['section'] == 'manager']
    zak_list = [e for e in employees if e['section'] == 'zak']
    zak = build_employee(zak_list[0]) if zak_list else None
    staff = [build_employee(e) for e in employees if e['section'] == 'staff']
    
    return {
        'weekTitle': schedule['week_title'],
        'weekStart': schedule['week_start'],
        'days': get_week_dates(week_start_str),
        'managers': managers,
        'zakReilly': zak,
        'employees': staff,
        'officeHours': office_hours,
        'events': [events_by_day[i] for i in range(7)]
    }


# =============================================================================
# ERROR HANDLERS
# =============================================================================

def register_error_handlers(app):
    """Register error handlers"""
    
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'error': 'Bad request', 'message': str(e)}), 400
    
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Not found', 'message': str(e)}), 404
    
    @app.errorhandler(500)
    def internal_error(e):
        logging.error(f"Internal error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# ROUTES
# =============================================================================

def register_routes(app):
    """Register all application routes"""
    
    @app.teardown_appcontext
    def teardown(exception):
        close_db()
    
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    # -------------------------------------------------------------------------
    # Pages
    # -------------------------------------------------------------------------
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    # -------------------------------------------------------------------------
    # Schedule API
    # -------------------------------------------------------------------------
    
    @app.route('/api/current-week', methods=['GET'])
    def get_current_week():
        """Get the current schedule week start date"""
        today = date.today()
        return jsonify({
            'weekStart': get_current_week_start(),
            'today': today.isoformat(),
            'todayName': today.strftime('%A')
        })
    
    @app.route('/api/schedule/<week_start>', methods=['GET'])
    def get_schedule(week_start):
        """Get schedule for a specific week"""
        try:
            return jsonify(build_schedule_response(week_start))
        except Exception as e:
            logging.error(f"Error getting schedule: {e}")
            return jsonify({'error': str(e)}), 400
    
    @app.route('/api/schedule/<week_start>', methods=['POST'])
    def save_schedule(week_start):
        """Save/update schedule for a specific week"""
        try:
            data = request.json
            logging.info(f"Saving schedule for week: {week_start}")
            logging.info(f"Payload: {data}")
            
            schedule = get_or_create_schedule(week_start)
            schedule_id = schedule['id']
            
            db = get_db()
            cursor = db.cursor()
            
            # Update shifts
            if 'shifts' in data:
                cursor.execute('DELETE FROM shifts WHERE schedule_id = ?', (schedule_id,))
                for shift in data['shifts']:
                    if shift.get('in') or shift.get('out'):
                        cursor.execute(
                            '''INSERT INTO shifts 
                               (schedule_id, employee_id, day_index, time_in, time_out) 
                               VALUES (?, ?, ?, ?, ?)''',
                            (schedule_id, shift['employee_id'], shift['day_index'],
                             shift.get('in'), shift.get('out'))
                        )
            
            # Update office hours
            if 'officeHours' in data:
                cursor.execute('DELETE FROM office_hours WHERE schedule_id = ?', (schedule_id,))
                for i, oh in enumerate(data['officeHours']):
                    cursor.execute(
                        '''INSERT INTO office_hours 
                           (schedule_id, day_index, time_in, time_out) 
                           VALUES (?, ?, ?, ?)''',
                        (schedule_id, i, oh.get('in'), oh.get('out'))
                    )
            
            # Update events
            if 'events' in data:
                cursor.execute('DELETE FROM events WHERE schedule_id = ?', (schedule_id,))
                for i, day_events in enumerate(data['events']):
                    if day_events:
                        for event_text in day_events:
                            if event_text:
                                cursor.execute(
                                    '''INSERT INTO events 
                                       (schedule_id, day_index, event_text) 
                                       VALUES (?, ?, ?)''',
                                    (schedule_id, i, event_text)
                                )
            
            # Update timestamp
            cursor.execute(
                'UPDATE schedules SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (schedule_id,)
            )
            
            db.commit()
            logging.info(f"Schedule saved successfully for week: {week_start}")
            return jsonify({'success': True, 'message': 'Schedule saved'})
        
        except Exception as e:
            import traceback
            logging.error(f"Error saving schedule: {e}")
            logging.error(traceback.format_exc())
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 400
    
    @app.route('/api/schedule/<week_start>/shift', methods=['POST'])
    def update_shift(week_start):
        """Update a single shift"""
        try:
            data = request.json
            schedule = get_or_create_schedule(week_start)
            
            db = get_db()
            cursor = db.cursor()
            
            # Delete existing shift
            cursor.execute(
                '''DELETE FROM shifts 
                   WHERE schedule_id = ? AND employee_id = ? AND day_index = ?''',
                (schedule['id'], data['employee_id'], data['day_index'])
            )
            
            # Insert new shift if values provided
            if data.get('in') or data.get('out'):
                cursor.execute(
                    '''INSERT INTO shifts 
                       (schedule_id, employee_id, day_index, time_in, time_out) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (schedule['id'], data['employee_id'], data['day_index'],
                     data.get('in'), data.get('out'))
                )
            
            db.commit()
            return jsonify({'success': True})
        
        except Exception as e:
            logging.error(f"Error updating shift: {e}")
            return jsonify({'error': str(e)}), 400
    
    # -------------------------------------------------------------------------
    # Employee API
    # -------------------------------------------------------------------------
    
    @app.route('/api/employees', methods=['GET'])
    def get_employees():
        """Get all active employees"""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            '''SELECT * FROM employees 
               WHERE active = 1 
               ORDER BY section, sort_order'''
        )
        return jsonify([dict(row) for row in cursor.fetchall()])
    
    @app.route('/api/employees', methods=['POST'])
    def add_employee():
        """Add a new employee"""
        try:
            data = request.json
            
            if not data.get('name'):
                return jsonify({'error': 'Name is required'}), 400
            
            section = data.get('section', 'staff')
            if section not in ('manager', 'zak', 'staff'):
                return jsonify({'error': 'Invalid section'}), 400
            
            db = get_db()
            cursor = db.cursor()
            
            # Get next sort order
            cursor.execute(
                'SELECT COALESCE(MAX(sort_order), 0) + 1 FROM employees WHERE section = ?',
                (section,)
            )
            next_order = cursor.fetchone()[0]
            
            cursor.execute(
                '''INSERT INTO employees (name, phone, section, sort_order) 
                   VALUES (?, ?, ?, ?)''',
                (data['name'], data.get('phone', ''), section, next_order)
            )
            
            emp_id = cursor.lastrowid
            cursor.execute('SELECT * FROM employees WHERE id = ?', (emp_id,))
            employee = dict(cursor.fetchone())
            
            db.commit()
            return jsonify(employee), 201
        
        except Exception as e:
            logging.error(f"Error adding employee: {e}")
            return jsonify({'error': str(e)}), 400
    
    @app.route('/api/employees/<int:emp_id>', methods=['PUT'])
    def update_employee(emp_id):
        """Update an employee"""
        try:
            data = request.json
            db = get_db()
            cursor = db.cursor()
            
            # Build update query dynamically
            updates = []
            values = []
            
            for field in ['name', 'phone', 'sort_order']:
                if field in data:
                    updates.append(f'{field} = ?')
                    values.append(data[field])
            
            if updates:
                updates.append('updated_at = CURRENT_TIMESTAMP')
                values.append(emp_id)
                cursor.execute(
                    f'UPDATE employees SET {", ".join(updates)} WHERE id = ?',
                    values
                )
            
            cursor.execute('SELECT * FROM employees WHERE id = ?', (emp_id,))
            row = cursor.fetchone()
            
            if not row:
                return jsonify({'error': 'Employee not found'}), 404
            
            db.commit()
            return jsonify(dict(row))
        
        except Exception as e:
            logging.error(f"Error updating employee: {e}")
            return jsonify({'error': str(e)}), 400
    
    @app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
    def delete_employee(emp_id):
        """Soft delete an employee"""
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute(
                'UPDATE employees SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (emp_id,)
            )
            db.commit()
            return jsonify({'success': True})
        
        except Exception as e:
            logging.error(f"Error deleting employee: {e}")
            return jsonify({'error': str(e)}), 400
    
    # -------------------------------------------------------------------------
    # Employee Notes API
    # -------------------------------------------------------------------------
    
    @app.route('/api/notes/<week_start>/<int:emp_id>', methods=['GET'])
    def get_note(week_start, emp_id):
        """Get note for employee for a specific week"""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'SELECT note FROM employee_notes WHERE week_start = ? AND employee_id = ?',
            (week_start, emp_id)
        )
        row = cursor.fetchone()
        return jsonify({'note': row['note'] if row else ''})
    
    @app.route('/api/notes/<week_start>/<int:emp_id>', methods=['POST'])
    def save_note(week_start, emp_id):
        """Save note for employee for a specific week"""
        try:
            data = request.json
            note = data.get('note', '').strip()
            
            db = get_db()
            cursor = db.cursor()
            
            if note:
                cursor.execute(
                    '''INSERT INTO employee_notes (employee_id, week_start, note) 
                       VALUES (?, ?, ?)
                       ON CONFLICT(employee_id, week_start) 
                       DO UPDATE SET note = ?, updated_at = CURRENT_TIMESTAMP''',
                    (emp_id, week_start, note, note)
                )
            else:
                cursor.execute(
                    'DELETE FROM employee_notes WHERE employee_id = ? AND week_start = ?',
                    (emp_id, week_start)
                )
            
            db.commit()
            return jsonify({'success': True})
        
        except Exception as e:
            logging.error(f"Error saving note: {e}")
            return jsonify({'error': str(e)}), 400
    
    # -------------------------------------------------------------------------
    # Export API
    # -------------------------------------------------------------------------
    
    @app.route('/api/schedule/<week_start>/export', methods=['GET'])
    def export_schedule(week_start):
        """Export schedule to Excel with formatting"""
        try:
            data = build_schedule_response(week_start)
            
            wb = Workbook()
            ws = wb.active
            ws.title = "Schedule"
            
            # Styles
            yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
            green_fill = PatternFill(start_color="92D050", end_color="92D050", fill_type="solid")
            gray_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
            
            bold_font = Font(bold=True)
            red_bold_font = Font(bold=True, color="FF0000")
            title_font = Font(bold=True, size=14)
            
            thin_border = Border(
                left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin')
            )
            center_align = Alignment(horizontal='center', vertical='center')
            left_align = Alignment(horizontal='left', vertical='center')
            
            # Title row
            ws.merge_cells('A1:O1')
            ws['A1'] = f"Ice Line Office Schedule for week of {data['weekTitle']}"
            ws['A1'].font = title_font
            ws['A1'].alignment = center_align
            
            # Day headers
            col = 2
            for day in data['days']:
                for r in [2, 3]:
                    for c in [col, col + 1]:
                        ws.cell(row=r, column=c).fill = gray_fill
                        ws.cell(row=r, column=c).alignment = center_align
                        ws.cell(row=r, column=c).border = thin_border
                ws.cell(row=2, column=col, value=day['name'])
                ws.cell(row=2, column=col + 1, value=day['date'])
                ws.cell(row=3, column=col, value='In')
                ws.cell(row=3, column=col + 1, value='Out')
                col += 2
            
            current_row = 4
            
            def write_employee_row(emp, row, fill=None):
                name = emp['name'] + ('     ' + emp['phone'] if emp.get('phone') else '')
                ws.cell(row=row, column=1, value=name).alignment = left_align
                ws.cell(row=row, column=1).border = thin_border
                if fill:
                    ws.cell(row=row, column=1).fill = fill
                    ws.cell(row=row, column=1).font = bold_font
                
                col = 2
                for shift in emp['shifts']:
                    in_val = shift['in'] if shift else ''
                    out_val = shift['out'] if shift else ''
                    for c, v in [(col, in_val), (col + 1, out_val)]:
                        ws.cell(row=row, column=c, value=v).alignment = center_align
                        ws.cell(row=row, column=c).border = thin_border
                        if fill:
                            ws.cell(row=row, column=c).fill = fill
                    col += 2
            
            # Managers
            for emp in data['managers']:
                write_employee_row(emp, current_row, yellow_fill)
                current_row += 1
            
            current_row += 1  # Empty row
            
            # Zak
            if data['zakReilly']:
                write_employee_row(data['zakReilly'], current_row, green_fill)
                current_row += 1
            
            current_row += 4  # Empty rows
            
            # Staff
            for emp in data['employees']:
                write_employee_row(emp, current_row, None)
                current_row += 1
            
            # Office Hours
            ws.cell(row=current_row, column=1, value='Front Office Hours*')
            ws.cell(row=current_row, column=1).fill = yellow_fill
            ws.cell(row=current_row, column=1).font = bold_font
            ws.cell(row=current_row, column=1).alignment = left_align
            ws.cell(row=current_row, column=1).border = thin_border
            
            col = 2
            for oh in data['officeHours']:
                for c, v in [(col, oh['in']), (col + 1, oh['out'])]:
                    ws.cell(row=current_row, column=c, value=v).fill = yellow_fill
                    ws.cell(row=current_row, column=c).alignment = center_align
                    ws.cell(row=current_row, column=c).border = thin_border
                col += 2
            current_row += 1
            
            # Notice row
            ws.cell(row=current_row, column=1, value='* Hours are subject to change')
            ws.cell(row=current_row, column=3, 
                    value='IF UNABLE TO WORK A SCHEDULED SHIFT YOU MUST FIND A REPLACEMENT')
            ws.cell(row=current_row, column=3).fill = green_fill
            ws.cell(row=current_row, column=3).font = red_bold_font
            current_row += 1
            
            # Events row
            ws.cell(row=current_row, column=1, value='Special Events:')
            ws.cell(row=current_row, column=1).fill = yellow_fill
            ws.cell(row=current_row, column=1).font = bold_font
            col = 2
            for events in data['events']:
                ws.cell(row=current_row, column=col, 
                        value=', '.join(events) if events else '').alignment = center_align
                col += 2
            
            # Column widths
            ws.column_dimensions['A'].width = 35
            for c in range(2, 16):
                ws.column_dimensions[get_column_letter(c)].width = 10
            
            # Save to buffer
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            
            # Generate filename
            d1 = data['days'][0]['date'].replace('/', '-')
            d2 = data['days'][6]['date'].replace('/', '-')
            year = data['weekTitle'].split(', ')[-1][-2:]
            filename = f"schedule_{d1}-{year}_to_{d2}-{year}.xlsx"
            
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )
        
        except Exception as e:
            logging.error(f"Error exporting schedule: {e}")
            return jsonify({'error': str(e)}), 400

    # -------------------------------------------------------------------------
    # Database Export/Import API
    # -------------------------------------------------------------------------
    
    @app.route('/api/backup/export', methods=['GET'])
    def export_database():
        """Export entire database to JSON for backup"""
        try:
            db = get_db()
            cursor = db.cursor()
            
            backup_data = {
                'export_date': datetime.now().isoformat(),
                'version': '1.0',
                'employees': [],
                'schedules': [],
                'shifts': [],
                'office_hours': [],
                'events': [],
                'employee_notes': []
            }
            
            # Export employees
            cursor.execute('SELECT * FROM employees')
            for row in cursor.fetchall():
                backup_data['employees'].append(dict(row))
            
            # Export schedules
            cursor.execute('SELECT * FROM schedules')
            for row in cursor.fetchall():
                backup_data['schedules'].append(dict(row))
            
            # Export shifts
            cursor.execute('SELECT * FROM shifts')
            for row in cursor.fetchall():
                backup_data['shifts'].append(dict(row))
            
            # Export office hours
            cursor.execute('SELECT * FROM office_hours')
            for row in cursor.fetchall():
                backup_data['office_hours'].append(dict(row))
            
            # Export events
            cursor.execute('SELECT * FROM events')
            for row in cursor.fetchall():
                backup_data['events'].append(dict(row))
            
            # Export employee notes
            cursor.execute('SELECT * FROM employee_notes')
            for row in cursor.fetchall():
                backup_data['employee_notes'].append(dict(row))
            
            # Create JSON file response
            import json
            output = BytesIO()
            output.write(json.dumps(backup_data, indent=2).encode('utf-8'))
            output.seek(0)
            
            filename = f"schedule_backup_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json"
            
            return send_file(
                output,
                mimetype='application/json',
                as_attachment=True,
                download_name=filename
            )
        
        except Exception as e:
            logging.error(f"Error exporting database: {e}")
            return jsonify({'error': str(e)}), 400
    
    @app.route('/api/backup/import', methods=['POST'])
    def import_database():
        """Import database from JSON backup"""
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'No file provided'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            import json
            backup_data = json.load(file)
            
            # Validate backup structure
            required_keys = ['employees', 'schedules', 'shifts', 'office_hours', 'events']
            for key in required_keys:
                if key not in backup_data:
                    return jsonify({'error': f'Invalid backup file: missing {key}'}), 400
            
            db = get_db()
            cursor = db.cursor()
            
            # Clear existing data (in reverse order of dependencies)
            cursor.execute('DELETE FROM employee_notes')
            cursor.execute('DELETE FROM events')
            cursor.execute('DELETE FROM office_hours')
            cursor.execute('DELETE FROM shifts')
            cursor.execute('DELETE FROM schedules')
            cursor.execute('DELETE FROM employees')
            
            # Import employees
            for emp in backup_data['employees']:
                cursor.execute('''
                    INSERT INTO employees (id, name, phone, section, sort_order, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (emp['id'], emp['name'], emp.get('phone', ''), emp['section'], 
                      emp.get('sort_order', 1), emp.get('active', 1),
                      emp.get('created_at'), emp.get('updated_at')))
            
            # Import schedules
            for sched in backup_data['schedules']:
                cursor.execute('''
                    INSERT INTO schedules (id, week_start, week_title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (sched['id'], sched['week_start'], sched['week_title'],
                      sched.get('created_at'), sched.get('updated_at')))
            
            # Import shifts
            for shift in backup_data['shifts']:
                cursor.execute('''
                    INSERT INTO shifts (id, schedule_id, employee_id, day_index, time_in, time_out)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (shift['id'], shift['schedule_id'], shift['employee_id'],
                      shift['day_index'], shift.get('time_in'), shift.get('time_out')))
            
            # Import office hours
            for oh in backup_data['office_hours']:
                cursor.execute('''
                    INSERT INTO office_hours (id, schedule_id, day_index, time_in, time_out)
                    VALUES (?, ?, ?, ?, ?)
                ''', (oh['id'], oh['schedule_id'], oh['day_index'],
                      oh.get('time_in'), oh.get('time_out')))
            
            # Import events
            for event in backup_data['events']:
                cursor.execute('''
                    INSERT INTO events (id, schedule_id, day_index, event_text)
                    VALUES (?, ?, ?, ?)
                ''', (event['id'], event['schedule_id'], event['day_index'], event.get('event_text')))
            
            # Import employee notes (if present)
            if 'employee_notes' in backup_data:
                for note in backup_data['employee_notes']:
                    cursor.execute('''
                        INSERT INTO employee_notes (id, schedule_id, employee_id, note, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (note['id'], note['schedule_id'], note['employee_id'],
                          note.get('note'), note.get('created_at'), note.get('updated_at')))
            
            db.commit()
            
            return jsonify({
                'success': True,
                'message': 'Database restored successfully',
                'stats': {
                    'employees': len(backup_data['employees']),
                    'schedules': len(backup_data['schedules']),
                    'shifts': len(backup_data['shifts']),
                    'office_hours': len(backup_data['office_hours']),
                    'events': len(backup_data['events']),
                    'employee_notes': len(backup_data.get('employee_notes', []))
                }
            })
        
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid JSON file'}), 400
        except Exception as e:
            logging.error(f"Error importing database: {e}")
            return jsonify({'error': str(e)}), 400


# =============================================================================
# MAIN
# =============================================================================

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=Config.DEBUG)
