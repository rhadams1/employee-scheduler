"""
Ice Line Employee Scheduler - Flask Backend
Uses sqlite3 directly (no Flask-SQLAlchemy dependency)
"""

from flask import Flask, jsonify, request, send_file, render_template
from datetime import datetime, timedelta
import sqlite3
import os
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

app = Flask(__name__, static_folder='static', template_folder='templates')

basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(basedir, 'schedule.db')


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            section TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start DATE NOT NULL UNIQUE,
            week_title TEXT
        );
        
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            time_in TEXT,
            time_out TEXT
        );
        
        CREATE TABLE IF NOT EXISTS office_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            time_in TEXT,
            time_out TEXT
        );
        
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            event_text TEXT
        );
    ''')
    
    cursor.execute('SELECT COUNT(*) FROM employees')
    if cursor.fetchone()[0] == 0:
        employees = [
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
        cursor.executemany('INSERT INTO employees (name, phone, section, sort_order) VALUES (?, ?, ?, ?)', employees)
        print("Initialized default employees")
    
    conn.commit()
    conn.close()


def get_week_dates(week_start_str):
    week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
    days = []
    day_names = ['Wed', 'Thurs', 'Fri', 'Sat', 'Sun', 'Mon', 'Tues']
    wed = week_start + timedelta(days=2)
    
    for i, name in enumerate(day_names):
        d = wed + timedelta(days=i)
        days.append({
            'name': name,
            'date': f"{d.month}/{d.day}",
            'isWeekend': name in ['Sat', 'Sun']
        })
    return days


def format_week_title(wed_date):
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    day = wed_date.day
    suffix = 'th'
    if day in [1, 21, 31]: suffix = 'st'
    elif day in [2, 22]: suffix = 'nd'
    elif day in [3, 23]: suffix = 'rd'
    return f"{months[wed_date.month - 1]} {day}{suffix}, {wed_date.year}"


def get_or_create_schedule(week_start_str):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM schedules WHERE week_start = ?', (week_start_str,))
    schedule = cursor.fetchone()
    
    if not schedule:
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        wed = week_start + timedelta(days=2)
        week_title = format_week_title(wed)
        
        cursor.execute('INSERT INTO schedules (week_start, week_title) VALUES (?, ?)', (week_start_str, week_title))
        schedule_id = cursor.lastrowid
        
        for i in range(7):
            cursor.execute('INSERT INTO office_hours (schedule_id, day_index, time_in, time_out) VALUES (?, ?, ?, ?)',
                          (schedule_id, i, '8:00 AM', '10:00 PM'))
        
        conn.commit()
        cursor.execute('SELECT * FROM schedules WHERE id = ?', (schedule_id,))
        schedule = cursor.fetchone()
    
    conn.close()
    return dict(schedule)


def build_schedule_response(week_start_str):
    conn = get_db()
    cursor = conn.cursor()
    
    schedule = get_or_create_schedule(week_start_str)
    schedule_id = schedule['id']
    
    cursor.execute('''SELECT * FROM employees WHERE active = 1 
                     ORDER BY CASE section WHEN 'manager' THEN 1 WHEN 'zak' THEN 2 WHEN 'staff' THEN 3 END, sort_order''')
    employees = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM shifts WHERE schedule_id = ?', (schedule_id,))
    shifts = {(row['employee_id'], row['day_index']): {'in': row['time_in'], 'out': row['time_out']} 
              for row in cursor.fetchall()}
    
    cursor.execute('SELECT * FROM office_hours WHERE schedule_id = ? ORDER BY day_index', (schedule_id,))
    oh_rows = cursor.fetchall()
    oh_dict = {row['day_index']: row for row in oh_rows}
    office_hours = [{'in': oh_dict[i]['time_in'], 'out': oh_dict[i]['time_out']} if i in oh_dict 
                    else {'in': '8:00 AM', 'out': '10:00 PM'} for i in range(7)]
    
    cursor.execute('SELECT * FROM events WHERE schedule_id = ?', (schedule_id,))
    events_by_day = {i: [] for i in range(7)}
    for row in cursor.fetchall():
        if row['event_text']:
            events_by_day[row['day_index']].append(row['event_text'])
    events = [events_by_day[i] for i in range(7)]
    
    conn.close()
    
    def build_emp(emp):
        return {
            'id': emp['id'],
            'name': emp['name'],
            'phone': emp['phone'] or '',
            'shifts': [shifts.get((emp['id'], i)) for i in range(7)]
        }
    
    managers = [build_emp(e) for e in employees if e['section'] == 'manager']
    zak_list = [e for e in employees if e['section'] == 'zak']
    zak = build_emp(zak_list[0]) if zak_list else None
    staff = [build_emp(e) for e in employees if e['section'] == 'staff']
    
    return {
        'weekTitle': schedule['week_title'],
        'weekStart': schedule['week_start'],
        'days': get_week_dates(week_start_str),
        'managers': managers,
        'zakReilly': zak,
        'employees': staff,
        'officeHours': office_hours,
        'events': events
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/current-week', methods=['GET'])
def get_current_week():
    """Get the current schedule week start date (Monday before Wednesday)"""
    from datetime import date
    today = date.today()
    
    # Python weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    weekday = today.weekday()
    
    # Schedule runs Wed-Tues
    # If today is Mon(0) or Tue(1), we're still in the previous week's schedule
    # If today is Wed(2)-Sun(6), we're in this week's schedule
    if weekday < 2:  # Monday or Tuesday
        # Go back to previous Monday
        days_back = 7 + weekday
    else:
        # Go back to this Monday
        days_back = weekday
    
    monday = today - timedelta(days=days_back)
    
    return jsonify({
        'weekStart': monday.isoformat(),
        'today': today.isoformat(),
        'todayName': today.strftime('%A')
    })


@app.route('/api/schedule/<week_start>', methods=['GET'])
def get_schedule(week_start):
    try:
        return jsonify(build_schedule_response(week_start))
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/schedule/<week_start>', methods=['POST'])
def save_schedule(week_start):
    try:
        data = request.json
        schedule = get_or_create_schedule(week_start)
        schedule_id = schedule['id']
        
        conn = get_db()
        cursor = conn.cursor()
        
        if 'shifts' in data:
            cursor.execute('DELETE FROM shifts WHERE schedule_id = ?', (schedule_id,))
            for s in data['shifts']:
                if s.get('in') or s.get('out'):
                    cursor.execute('INSERT INTO shifts (schedule_id, employee_id, day_index, time_in, time_out) VALUES (?, ?, ?, ?, ?)',
                                  (schedule_id, s['employee_id'], s['day_index'], s.get('in'), s.get('out')))
        
        if 'officeHours' in data:
            cursor.execute('DELETE FROM office_hours WHERE schedule_id = ?', (schedule_id,))
            for i, oh in enumerate(data['officeHours']):
                cursor.execute('INSERT INTO office_hours (schedule_id, day_index, time_in, time_out) VALUES (?, ?, ?, ?)',
                              (schedule_id, i, oh.get('in'), oh.get('out')))
        
        if 'events' in data:
            cursor.execute('DELETE FROM events WHERE schedule_id = ?', (schedule_id,))
            for i, day_events in enumerate(data['events']):
                for evt in day_events:
                    if evt:
                        cursor.execute('INSERT INTO events (schedule_id, day_index, event_text) VALUES (?, ?, ?)',
                                      (schedule_id, i, evt))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/schedule/<week_start>/shift', methods=['POST'])
def update_shift(week_start):
    try:
        data = request.json
        schedule = get_or_create_schedule(week_start)
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM shifts WHERE schedule_id = ? AND employee_id = ? AND day_index = ?',
                      (schedule['id'], data['employee_id'], data['day_index']))
        
        if data.get('in') or data.get('out'):
            cursor.execute('INSERT INTO shifts (schedule_id, employee_id, day_index, time_in, time_out) VALUES (?, ?, ?, ?, ?)',
                          (schedule['id'], data['employee_id'], data['day_index'], data.get('in'), data.get('out')))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/employees', methods=['GET'])
def get_employees():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM employees WHERE active = 1 ORDER BY section, sort_order')
    employees = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(employees)


@app.route('/api/employees', methods=['POST'])
def add_employee():
    try:
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT MAX(sort_order) FROM employees WHERE section = ?', (data.get('section', 'staff'),))
        max_order = cursor.fetchone()[0] or 0
        
        cursor.execute('INSERT INTO employees (name, phone, section, sort_order) VALUES (?, ?, ?, ?)',
                      (data['name'], data.get('phone', ''), data.get('section', 'staff'), max_order + 1))
        emp_id = cursor.lastrowid
        
        cursor.execute('SELECT * FROM employees WHERE id = ?', (emp_id,))
        employee = dict(cursor.fetchone())
        
        conn.commit()
        conn.close()
        return jsonify(employee), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/employees/<int:emp_id>', methods=['PUT'])
def update_employee(emp_id):
    try:
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        
        if 'name' in data:
            cursor.execute('UPDATE employees SET name = ? WHERE id = ?', (data['name'], emp_id))
        if 'phone' in data:
            cursor.execute('UPDATE employees SET phone = ? WHERE id = ?', (data['phone'], emp_id))
        if 'sort_order' in data:
            cursor.execute('UPDATE employees SET sort_order = ? WHERE id = ?', (data['sort_order'], emp_id))
        
        cursor.execute('SELECT * FROM employees WHERE id = ?', (emp_id,))
        employee = dict(cursor.fetchone())
        
        conn.commit()
        conn.close()
        return jsonify(employee)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
def delete_employee(emp_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE employees SET active = 0 WHERE id = ?', (emp_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/schedule/<week_start>/export', methods=['GET'])
def export_schedule(week_start):
    try:
        data = build_schedule_response(week_start)
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        
        yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
        green_fill = PatternFill(start_color="92D050", end_color="92D050", fill_type="solid")
        gray_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        
        bold_font = Font(bold=True)
        red_bold_font = Font(bold=True, color="FF0000")
        title_font = Font(bold=True, size=14)
        
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'),
                            top=Side(style='thin'), bottom=Side(style='thin'))
        center_align = Alignment(horizontal='center', vertical='center')
        left_align = Alignment(horizontal='left', vertical='center')
        
        ws.merge_cells('A1:O1')
        ws['A1'] = f"Ice Line Office Schedule for week of {data['weekTitle']}"
        ws['A1'].font = title_font
        ws['A1'].alignment = center_align
        
        col = 2
        for day in data['days']:
            for r in [2, 3]:
                ws.cell(row=r, column=col).fill = gray_fill
                ws.cell(row=r, column=col).alignment = center_align
                ws.cell(row=r, column=col).border = thin_border
                ws.cell(row=r, column=col+1).fill = gray_fill
                ws.cell(row=r, column=col+1).alignment = center_align
                ws.cell(row=r, column=col+1).border = thin_border
            ws.cell(row=2, column=col, value=day['name'])
            ws.cell(row=2, column=col+1, value=day['date'])
            ws.cell(row=3, column=col, value='In')
            ws.cell(row=3, column=col+1, value='Out')
            col += 2
        
        current_row = 4
        
        def write_emp(emp, row, fill=None):
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
                for c, v in [(col, in_val), (col+1, out_val)]:
                    ws.cell(row=row, column=c, value=v).alignment = center_align
                    ws.cell(row=row, column=c).border = thin_border
                    if fill:
                        ws.cell(row=row, column=c).fill = fill
                col += 2
        
        for emp in data['managers']:
            write_emp(emp, current_row, yellow_fill)
            current_row += 1
        
        current_row += 1
        
        if data['zakReilly']:
            write_emp(data['zakReilly'], current_row, green_fill)
            current_row += 1
        
        current_row += 4
        
        for emp in data['employees']:
            write_emp(emp, current_row, None)
            current_row += 1
        
        ws.cell(row=current_row, column=1, value='Front Office Hours*')
        ws.cell(row=current_row, column=1).fill = yellow_fill
        ws.cell(row=current_row, column=1).font = bold_font
        ws.cell(row=current_row, column=1).alignment = left_align
        ws.cell(row=current_row, column=1).border = thin_border
        
        col = 2
        for oh in data['officeHours']:
            for c, v in [(col, oh['in']), (col+1, oh['out'])]:
                ws.cell(row=current_row, column=c, value=v).fill = yellow_fill
                ws.cell(row=current_row, column=c).alignment = center_align
                ws.cell(row=current_row, column=c).border = thin_border
            col += 2
        current_row += 1
        
        ws.cell(row=current_row, column=1, value='* Hours are subject to change')
        ws.cell(row=current_row, column=3, value='IF UNABLE TO WORK A SCHEDULED SHIFT YOU MUST FIND A REPLACEMENT')
        ws.cell(row=current_row, column=3).fill = green_fill
        ws.cell(row=current_row, column=3).font = red_bold_font
        current_row += 1
        
        ws.cell(row=current_row, column=1, value='Special Events:')
        ws.cell(row=current_row, column=1).fill = yellow_fill
        ws.cell(row=current_row, column=1).font = bold_font
        col = 2
        for evts in data['events']:
            ws.cell(row=current_row, column=col, value=', '.join(evts) if evts else '').alignment = center_align
            col += 2
        
        ws.column_dimensions['A'].width = 35
        for c in range(2, 16):
            ws.column_dimensions[get_column_letter(c)].width = 10
        
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        d1 = data['days'][0]['date'].replace('/', '-')
        d2 = data['days'][6]['date'].replace('/', '-')
        year = data['weekTitle'].split(', ')[-1][-2:]
        filename = f"{d1}-{year}__to__{d2}-{year}.xlsx"
        
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5001, debug=True)
