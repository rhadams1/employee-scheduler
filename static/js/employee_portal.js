/**
 * Ice Line Employee Portal
 * Read-only schedule view for employees
 */

// State
let scheduleData = null;
let currentWeekStart = null;
let selectedEmployee = 'all';

// Day abbreviations
const dayNames = ['Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon', 'Tue'];

// Initialize on page load
document.addEventListener('DOMContentLoaded', init);

async function init() {
    try {
        // Get current week
        const response = await fetch('/api/current-week');
        const data = await response.json();
        currentWeekStart = data.weekStart;
        
        await loadSchedule();
    } catch (error) {
        console.error('Error initializing:', error);
        showError('Failed to load schedule. Please try again.');
    }
}

async function loadSchedule() {
    try {
        const response = await fetch(`/api/schedule/${currentWeekStart}`);
        if (!response.ok) throw new Error('Failed to load schedule');
        
        scheduleData = await response.json();
        
        updateWeekTitle();
        populateEmployeeFilter();
        renderSchedule();
        renderOfficeHours();
        renderEvents();
        updateTimestamp();
    } catch (error) {
        console.error('Error loading schedule:', error);
        showError('Failed to load schedule.');
    }
}

async function navigateWeek(direction) {
    const current = new Date(currentWeekStart);
    current.setDate(current.getDate() + (direction * 7));
    currentWeekStart = current.toISOString().split('T')[0];
    
    await loadSchedule();
}

function updateWeekTitle() {
    const titleEl = document.getElementById('weekTitle');
    if (titleEl && scheduleData) {
        titleEl.textContent = scheduleData.weekTitle;
    }
}

function populateEmployeeFilter() {
    const select = document.getElementById('employeeFilter');
    if (!select || !scheduleData) return;
    
    // Keep current selection
    const currentValue = select.value;
    
    // Clear and rebuild options
    select.innerHTML = '<option value="all">All Employees</option>';
    
    // Add all employees
    const allEmployees = [
        ...scheduleData.managers.map(e => ({ ...e, section: 'manager' })),
        { ...scheduleData.zakReilly, section: 'zak' },
        ...scheduleData.employees.map(e => ({ ...e, section: 'staff' }))
    ].filter(e => e && e.name);
    
    allEmployees.forEach(emp => {
        const option = document.createElement('option');
        option.value = emp.id;
        option.textContent = emp.name;
        select.appendChild(option);
    });
    
    // Restore selection
    select.value = currentValue || 'all';
}

function filterSchedule() {
    const select = document.getElementById('employeeFilter');
    selectedEmployee = select.value;
    renderSchedule();
}

function renderSchedule() {
    const container = document.getElementById('scheduleContainer');
    if (!container || !scheduleData) return;
    
    const allEmployees = [
        ...scheduleData.managers.map(e => ({ ...e, section: 'manager' })),
        { ...scheduleData.zakReilly, section: 'zak' },
        ...scheduleData.employees.map(e => ({ ...e, section: 'staff' }))
    ].filter(e => e && e.name);
    
    // Filter if needed
    const employeesToShow = selectedEmployee === 'all' 
        ? allEmployees 
        : allEmployees.filter(e => e.id.toString() === selectedEmployee);
    
    if (employeesToShow.length === 0) {
        container.innerHTML = `
            <div class="no-shifts">
                <div class="no-shifts-icon"></div>
                <p>No employees found</p>
            </div>
        `;
        return;
    }
    
    const html = employeesToShow.map(emp => renderEmployeeCard(emp)).join('');
    container.innerHTML = html;
}

function renderEmployeeCard(employee) {
    const isHighlighted = selectedEmployee !== 'all' && employee.id.toString() === selectedEmployee;
    const sectionClass = employee.section;
    const highlightClass = isHighlighted ? 'highlighted' : '';
    
    // Calculate total hours
    const totalHours = calculateHours(employee.shifts);
    const overtimeClass = totalHours > 40 ? 'overtime' : '';
    
    // Phone link
    const phoneHtml = employee.phone 
        ? `<a href="tel:${employee.phone.replace(/\D/g, '')}">${employee.phone}</a>`
        : '';
    
    // Build shifts grid
    const shiftsHtml = scheduleData.days.map((day, i) => {
        const shift = employee.shifts[i];
        const isWeekend = day.isWeekend;
        const isToday = isDateToday(day.fullDate);
        const isOff = !shift || (!shift.in && !shift.out) || (shift.in === '-');
        
        let classes = ['shift-day'];
        if (isWeekend) classes.push('weekend');
        if (isToday) classes.push('today');
        if (isOff) classes.push('off');
        
        let shiftContent = '';
        if (isOff) {
            shiftContent = '<span class="shift-time off">—</span>';
        } else {
            const inTime = formatTimeShort(shift.in);
            const outTime = formatTimeShort(shift.out);
            shiftContent = `
                <span class="shift-time">
                    <span class="in-time">${inTime}</span>
                    <span class="out-time">${outTime}</span>
                </span>
            `;
        }
        
        return `
            <div class="${classes.join(' ')}">
                <span class="day-label">${dayNames[i]}</span>
                <span class="day-date">${day.date}</span>
                ${shiftContent}
            </div>
        `;
    }).join('');
    
    return `
        <div class="employee-card ${sectionClass} ${highlightClass}">
            <div class="employee-header">
                <div>
                    <div class="employee-name">${employee.name}</div>
                    <div class="employee-phone">${phoneHtml}</div>
                </div>
                ${totalHours > 0 ? `<span class="total-hours ${overtimeClass}">${totalHours.toFixed(1)} hrs</span>` : ''}
            </div>
            <div class="shifts-grid">
                ${shiftsHtml}
            </div>
        </div>
    `;
}

function renderOfficeHours() {
    const grid = document.getElementById('officeHoursGrid');
    if (!grid || !scheduleData) return;
    
    const html = scheduleData.days.map((day, i) => {
        const oh = scheduleData.officeHours[i];
        const isWeekend = day.isWeekend;
        const weekendClass = isWeekend ? 'weekend' : '';
        
        let hoursText = '';
        let hoursClass = '';
        
        if (oh.in === 'CLOSED') {
            hoursText = 'CLOSED';
            hoursClass = 'closed';
        } else if (oh.in && oh.out) {
            hoursText = `${formatTimeShort(oh.in)} - ${formatTimeShort(oh.out)}`;
        } else {
            hoursText = '—';
        }
        
        return `
            <div class="office-day ${weekendClass}">
                <div class="day-name">${dayNames[i]}</div>
                <div class="hours ${hoursClass}">${hoursText}</div>
            </div>
        `;
    }).join('');
    
    grid.innerHTML = html;
}

function renderEvents() {
    const card = document.getElementById('eventsCard');
    const list = document.getElementById('eventsList');
    if (!card || !list || !scheduleData) return;
    
    // Collect all events
    const allEvents = [];
    scheduleData.events.forEach((events, dayIndex) => {
        if (events && events.length > 0) {
            events.forEach(eventText => {
                if (eventText) {
                    allEvents.push({
                        day: scheduleData.days[dayIndex],
                        dayIndex,
                        text: eventText
                    });
                }
            });
        }
    });
    
    if (allEvents.length === 0) {
        card.style.display = 'none';
        return;
    }
    
    card.style.display = 'block';
    
    const html = allEvents.map(event => `
        <div class="event-item">
            <span class="event-day">${dayNames[event.dayIndex]} ${event.day.date}:</span>
            <span class="event-text">${event.text}</span>
        </div>
    `).join('');
    
    list.innerHTML = html;
}

function updateTimestamp() {
    const el = document.getElementById('updatedTime');
    if (el) {
        const now = new Date();
        el.textContent = `Last updated: ${now.toLocaleString()}`;
    }
}

// Utility Functions
function calculateHours(shifts) {
    let total = 0;
    
    shifts.forEach(shift => {
        if (!shift || shift.in === '-' || !shift.in || !shift.out) return;
        
        const inTime = parseTime(shift.in);
        const outTime = parseTime(shift.out);
        
        if (inTime !== null && outTime !== null) {
            let hours = outTime - inTime;
            if (hours < 0) hours += 24; // Overnight shift
            total += hours;
        }
    });
    
    return total;
}

function parseTime(timeStr) {
    if (!timeStr || timeStr === '-' || timeStr === 'CLOSE' || timeStr === 'OPEN') return null;
    
    const match = timeStr.match(/(\d{1,2}):?(\d{2})?\s*(AM|PM)?/i);
    if (!match) return null;
    
    let hours = parseInt(match[1]);
    const minutes = parseInt(match[2] || '0');
    const period = match[3];
    
    if (period) {
        if (period.toUpperCase() === 'PM' && hours !== 12) hours += 12;
        if (period.toUpperCase() === 'AM' && hours === 12) hours = 0;
    }
    
    return hours + minutes / 60;
}

function formatTimeShort(timeStr) {
    if (!timeStr || timeStr === '-') return '—';
    if (timeStr === 'CLOSE' || timeStr === 'OPEN') return timeStr;
    
    // Already formatted nicely
    if (timeStr.includes('AM') || timeStr.includes('PM')) {
        // Remove leading zeros and make more compact
        return timeStr.replace(/^0/, '').replace(':00', '');
    }
    
    return timeStr;
}

function isDateToday(dateStr) {
    if (!dateStr) return false;
    const today = new Date();
    const checkDate = new Date(dateStr);
    return today.toDateString() === checkDate.toDateString();
}

function showError(message) {
    const container = document.getElementById('scheduleContainer');
    if (container) {
        container.innerHTML = `
            <div class="no-shifts">
                <div class="no-shifts-icon"></div>
                <p>${message}</p>
                <button class="nav-btn" onclick="location.reload()" style="margin-top: 16px;">Retry</button>
            </div>
        `;
    }
}
