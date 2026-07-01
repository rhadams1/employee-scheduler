"""Render the personalized weekly schedule bulletin email.

Pure functions of the schedule_data dict (build_schedule_response shape). Link-free:
no remote images or URLs. Returns (subject, html, text).
"""
import html as _html


def _fmt_shift(shift):
    """A single shift cell -> human string, or None if not working."""
    if not shift:
        return None
    tin, tout = shift.get('in'), shift.get('out')
    if not tin and not tout:
        return None
    if tin in ('-', '') and tout in ('-', ''):
        return None
    return f"{tin or '?'}–{tout or '?'}"  # en-dash between


def _all_people(schedule_data):
    people = list(schedule_data.get('managers', []))
    if schedule_data.get('zakReilly'):
        people.append(schedule_data['zakReilly'])
    people.extend(schedule_data.get('employees', []))
    return people


def _my_shift_lines(employee, days):
    """List of 'Wed 6/24  8:00 AM-4:00 PM' for the employee's working days."""
    lines = []
    for i, day in enumerate(days):
        s = _fmt_shift(employee['shifts'][i]) if i < len(employee['shifts']) else None
        if s:
            lines.append(f"{day['name']} {day['date']}  {s}")
    return lines


def _full_week_text(schedule_data):
    days = schedule_data['days']
    people = _all_people(schedule_data)
    office = schedule_data.get('officeHours', [])
    events = schedule_data.get('events', [])
    out = []
    for i, day in enumerate(days):
        oh = office[i] if i < len(office) else {}
        oh_str = ''
        if oh.get('in') and oh.get('out'):
            oh_str = f"  (office {oh['in']}–{oh['out']})"
        out.append(f"{day['name']} {day['date']}{oh_str}")
        ev = events[i] if i < len(events) else []
        if ev:
            out.append(f"    * {', '.join(ev)}")
        working = []
        for p in people:
            s = _fmt_shift(p['shifts'][i]) if i < len(p['shifts']) else None
            if s:
                working.append(f"{p['name']}: {s}")
        if working:
            for w in working:
                out.append(f"    {w}")
        else:
            out.append("    (no staff scheduled)")
        out.append("")
    return "\n".join(out).rstrip()


def render_bulletin(employee, schedule_data):
    week = schedule_data['weekTitle']
    subject = f"Ice Line schedule — week of {week}"

    mine = _my_shift_lines(employee, schedule_data['days'])
    mine_block = "\n".join(f"  {m}" for m in mine) if mine else "  (no shifts scheduled)"
    full = _full_week_text(schedule_data)

    text = (
        f"Hi {employee['name']} — your shifts for the week of {week}:\n"
        f"{mine_block}\n\n"
        f"{'-' * 40}\nFULL WEEK\n\n{full}\n"
    )

    def esc(s):
        return _html.escape(str(s))

    mine_html = ("<ul>" + "".join(f"<li>{esc(m)}</li>" for m in mine) + "</ul>") if mine \
        else "<p><em>No shifts scheduled.</em></p>"
    full_html = "<pre style=\"font-family:inherit;white-space:pre-wrap;margin:0\">" \
        + esc(full) + "</pre>"
    html = (
        "<div style=\"font-family:system-ui,Arial,sans-serif;max-width:560px;"
        "margin:0 auto;color:#222\">"
        f"<h2 style=\"color:#2d8cf0;margin:0 0 4px\">Ice Line Schedule</h2>"
        f"<p style=\"margin:0 0 12px;color:#666\">Week of {esc(week)}</p>"
        f"<p style=\"margin:0 0 4px\"><strong>Hi {esc(employee['name'])} — "
        f"your shifts:</strong></p>{mine_html}"
        f"<hr style=\"border:none;border-top:1px solid #ddd;margin:16px 0\">"
        f"<p style=\"margin:0 0 6px\"><strong>Full week</strong></p>{full_html}"
        "</div>"
    )
    return subject, html, text
