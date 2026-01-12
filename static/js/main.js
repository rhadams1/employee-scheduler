/**
 * Ice Line Employee Scheduler - Main JavaScript
 * Production-ready, extracted from monolithic HTML
 */

// =============================================================================
// CONFIGURATION
// =============================================================================

const Config = {
    API_BASE: '',
    AUTO_SAVE_DELAY: 1500,
    OVERTIME_THRESHOLD: 40,
    MAX_UNDO_HISTORY: 50,
};

// =============================================================================
// STATE
// =============================================================================

const State = {
    currentView: 'manager',
    currentWeekStart: null,
    hasUnsavedChanges: false,
    autoSaveTimer: null,
    undoStack: [],
    redoStack: [],
    currentEdit: null,
};

let scheduleData = {
    weekTitle: '',
    weekStart: '',
    days: [],
    managers: [],
    zakReilly: null,
    employees: [],
    officeHours: [],
    events: []
};

// =============================================================================
// TEMPLATES & HOLIDAYS
// =============================================================================

const shiftTemplates = [
    { name: 'Opener', in: '8:00 AM', out: '4:00 PM' },
    { name: 'Mid', in: '12:00 PM', out: '8:00 PM' },
    { name: 'Closer', in: '4:00 PM', out: 'CLOSE' },
    { name: 'Morning', in: '6:00 AM', out: '12:00 PM' },
    { name: 'Evening', in: '5:00 PM', out: '10:00 PM' },
    { name: 'Full Day', in: '8:00 AM', out: '10:00 PM' },
    { name: 'Off', in: '-', out: '-' },
];

const holidays = {
    '2025-01-01': "New Year's Day",
    '2025-01-20': 'MLK Day',
    '2025-02-17': "Presidents' Day",
    '2025-05-26': 'Memorial Day',
    '2025-07-04': 'Independence Day',
    '2025-09-01': 'Labor Day',
    '2025-10-13': 'Columbus Day',
    '2025-11-11': 'Veterans Day',
    '2025-11-27': 'Thanksgiving',
    '2025-11-28': 'Day After Thanksgiving',
    '2025-12-24': 'Christmas Eve',
    '2025-12-25': 'Christmas Day',
    '2025-12-31': "New Year's Eve",
    '2026-01-01': "New Year's Day",
    '2026-01-19': 'MLK Day',
    '2026-02-16': "Presidents' Day",
    '2026-05-25': 'Memorial Day',
    '2026-07-03': 'Independence Day (Observed)',
    '2026-07-04': 'Independence Day',
    '2026-09-07': 'Labor Day',
    '2026-10-12': 'Columbus Day',
    '2026-11-11': 'Veterans Day',
    '2026-11-26': 'Thanksgiving',
    '2026-11-27': 'Day After Thanksgiving',
    '2026-12-24': 'Christmas Eve',
    '2026-12-25': 'Christmas Day',
    '2026-12-31': "New Year's Eve",
};

// =============================================================================
// INITIALIZATION
// =============================================================================

document.addEventListener('DOMContentLoaded', async function() {
    loadDarkModePreference();
    
    try {
        const response = await fetch(`${Config.API_BASE}/api/current-week`);
        const data = await response.json();
        State.currentWeekStart = data.weekStart;
        console.log('Current week from server:', data);
    } catch (error) {
        console.error('Failed to get current week:', error);
        State.currentWeekStart = getWeekStartFallback(new Date());
    }
    
    await loadSchedule(State.currentWeekStart);
    renderSchedule();
    setupEventListeners();
    setupKeyboardShortcuts();
    
    console.log('Schedule loaded:', scheduleData);
});

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
            e.preventDefault();
            undo();
        }
        if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
            e.preventDefault();
            redo();
        }
        if (e.key === 'Escape') {
            closeModal();
        }
    });
}

function getWeekStartFallback(date) {
    const d = new Date(date);
    const day = d.getDay();
    let daysToMonday;
    if (day === 0) daysToMonday = 6;
    else if (day === 1) daysToMonday = 7;
    else if (day === 2) daysToMonday = 8;
    else daysToMonday = day - 1;
    d.setDate(d.getDate() - daysToMonday);
    return d.toISOString().split('T')[0];
}

// =============================================================================
// API FUNCTIONS
// =============================================================================

async function loadSchedule(weekStart) {
    try {
        const response = await fetch(`${Config.API_BASE}/api/schedule/${weekStart}`);
        if (!response.ok) throw new Error('Failed to load schedule');
        const data = await response.json();
        
        scheduleData = {
            weekTitle: data.weekTitle,
            weekStart: data.weekStart,
            days: data.days,
            managers: data.managers,
            zakReilly: data.zakReilly,
            employees: data.employees,
            officeHours: data.officeHours,
            events: data.events
        };
        
        State.currentWeekStart = weekStart;
        State.hasUnsavedChanges = false;
        return true;
    } catch (error) {
        console.error('Error loading schedule:', error);
        return false;
    }
}

async function saveSchedule() {
    try {
        const shifts = [];
        const allEmployees = [
            ...scheduleData.managers,
            scheduleData.zakReilly,
            ...scheduleData.employees
        ].filter(e => e);
        
        allEmployees.forEach(emp => {
            emp.shifts.forEach((shift, dayIndex) => {
                if (shift && (shift.in || shift.out)) {
                    shifts.push({
                        employee_id: emp.id,
                        day_index: dayIndex,
                        in: shift.in,
                        out: shift.out
                    });
                }
            });
        });
        
        const payload = {
            shifts,
            officeHours: scheduleData.officeHours,
            events: scheduleData.events
        };
        
        console.log('Saving schedule:', payload);
        
        const response = await fetch(`${Config.API_BASE}/api/schedule/${State.currentWeekStart}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const responseData = await response.json();
        console.log('Save response:', response.status, responseData);
        
        if (!response.ok) throw new Error(responseData.error || 'Failed to save schedule');
        
        State.hasUnsavedChanges = false;
        updateAutoSaveStatus('saved');
    } catch (error) {
        console.error('Error saving schedule:', error);
        updateAutoSaveStatus('error');
    }
}

// =============================================================================
// DARK MODE
// =============================================================================

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDark ? 'true' : 'false');
    
    const btn = document.querySelector('.dark-mode-toggle');
    if (btn) btn.textContent = isDark ? '☀️' : '🌙';
}

function loadDarkModePreference() {
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
    }
}

// =============================================================================
// BACKUP / RESTORE
// =============================================================================

function toggleBackupMenu() {
    const menu = document.getElementById('backupMenu');
    if (menu) {
        menu.classList.toggle('show');
    }
}

// Close backup menu when clicking outside
document.addEventListener('click', (e) => {
    const menu = document.getElementById('backupMenu');
    const btn = e.target.closest('.backup-dropdown');
    if (menu && !btn) {
        menu.classList.remove('show');
    }
});

function exportBackup() {
    window.location.href = `${Config.API_BASE}/api/backup/export`;
    toggleBackupMenu();
}

function triggerImport() {
    document.getElementById('importFileInput').click();
    toggleBackupMenu();
}

async function importBackup(input) {
    if (!input.files || !input.files[0]) return;
    
    const file = input.files[0];
    
    if (!confirm(`Are you sure you want to restore from "${file.name}"?\n\nThis will REPLACE all current data including employees, schedules, and shifts.`)) {
        input.value = '';
        return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch(`${Config.API_BASE}/api/backup/import`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(`Backup restored successfully!\n\nRestored:\n- ${result.stats.employees} employees\n- ${result.stats.schedules} schedules\n- ${result.stats.shifts} shifts`);
            // Reload the page to show restored data
            window.location.reload();
        } else {
            alert(`Error restoring backup: ${result.error}`);
        }
    } catch (error) {
        console.error('Error importing backup:', error);
        alert('Error importing backup. See console for details.');
    }
    
    input.value = '';
}

// =============================================================================
// UNDO / REDO
// =============================================================================

function saveStateForUndo() {
    const state = JSON.stringify({
        managers: scheduleData.managers,
        zakReilly: scheduleData.zakReilly,
        employees: scheduleData.employees,
        officeHours: scheduleData.officeHours,
        events: scheduleData.events
    });
    
    State.undoStack.push(state);
    if (State.undoStack.length > Config.MAX_UNDO_HISTORY) {
        State.undoStack.shift();
    }
    State.redoStack = [];
    updateUndoRedoButtons();
}

function undo() {
    if (State.undoStack.length === 0) return;
    
    const currentState = JSON.stringify({
        managers: scheduleData.managers,
        zakReilly: scheduleData.zakReilly,
        employees: scheduleData.employees,
        officeHours: scheduleData.officeHours,
        events: scheduleData.events
    });
    State.redoStack.push(currentState);
    
    const previousState = JSON.parse(State.undoStack.pop());
    Object.assign(scheduleData, previousState);
    
    updateUndoRedoButtons();
    renderSchedule();
    setupEventListeners();
    triggerAutoSave();
}

function redo() {
    if (State.redoStack.length === 0) return;
    
    const currentState = JSON.stringify({
        managers: scheduleData.managers,
        zakReilly: scheduleData.zakReilly,
        employees: scheduleData.employees,
        officeHours: scheduleData.officeHours,
        events: scheduleData.events
    });
    State.undoStack.push(currentState);
    
    const nextState = JSON.parse(State.redoStack.pop());
    Object.assign(scheduleData, nextState);
    
    updateUndoRedoButtons();
    renderSchedule();
    setupEventListeners();
    triggerAutoSave();
}

function updateUndoRedoButtons() {
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    if (undoBtn) undoBtn.disabled = State.undoStack.length === 0;
    if (redoBtn) redoBtn.disabled = State.redoStack.length === 0;
}

// =============================================================================
// AUTO-SAVE
// =============================================================================

function triggerAutoSave() {
    if (State.autoSaveTimer) clearTimeout(State.autoSaveTimer);
    updateAutoSaveStatus('saving');
    State.autoSaveTimer = setTimeout(async () => {
        await saveSchedule();
    }, Config.AUTO_SAVE_DELAY);
}

function updateAutoSaveStatus(status) {
    const el = document.getElementById('autoSaveStatus');
    if (!el) return;
    
    el.className = 'auto-save-status ' + status;
    const msgs = {
        saving: '<span class="icon">⏳</span> Saving...',
        saved: '<span class="icon">✓</span> Auto-saved',
        error: '<span class="icon">⚠</span> Save failed'
    };
    el.innerHTML = msgs[status] || '';
}

function markUnsaved() {
    State.hasUnsavedChanges = true;
    triggerAutoSave();
}

// =============================================================================
// WEEK NAVIGATION
// =============================================================================

async function navigateWeek(direction) {
    const current = new Date(State.currentWeekStart);
    current.setDate(current.getDate() + (direction * 7));
    const newWeekStart = current.toISOString().split('T')[0];
    
    await loadSchedule(newWeekStart);
    State.undoStack = [];
    State.redoStack = [];
    
    renderSchedule();
    setupEventListeners();
}

async function copyPreviousWeek() {
    const current = new Date(State.currentWeekStart);
    current.setDate(current.getDate() - 7);
    const prevWeekKey = current.toISOString().split('T')[0];
    
    if (!confirm('Copy shifts from previous week?')) return;
    
    try {
        const response = await fetch(`${Config.API_BASE}/api/schedule/${prevWeekKey}`);
        if (!response.ok) {
            alert('No schedule found for the previous week.');
            return;
        }
        
        saveStateForUndo();
        const prev = await response.json();
        
        scheduleData.managers.forEach((emp, i) => {
            if (prev.managers[i]) {
                emp.shifts = JSON.parse(JSON.stringify(prev.managers[i].shifts));
            }
        });
        
        if (prev.zakReilly && scheduleData.zakReilly) {
            scheduleData.zakReilly.shifts = JSON.parse(JSON.stringify(prev.zakReilly.shifts));
        }
        
        scheduleData.employees.forEach((emp, i) => {
            if (prev.employees[i]) {
                emp.shifts = JSON.parse(JSON.stringify(prev.employees[i].shifts));
            }
        });
        
        scheduleData.officeHours = JSON.parse(JSON.stringify(prev.officeHours));
        scheduleData.events = [[], [], [], [], [], [], []];
        
        markUnsaved();
        renderSchedule();
        setupEventListeners();
    } catch (error) {
        console.error('Error copying previous week:', error);
        alert('Failed to copy previous week.');
    }
}

// =============================================================================
// VIEW MANAGEMENT
// =============================================================================

function setView(view) {
    State.currentView = view;
    document.body.classList.toggle('employee-view', view === 'employee');
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });
}

function toggleCoverage() {
    const container = document.getElementById('coverageContainer');
    if (!container) return;
    
    const isVisible = container.style.display !== 'none';
    container.style.display = isVisible ? 'none' : 'block';
    
    if (!isVisible) {
        container.innerHTML = renderCoverageView();
    }
}

// =============================================================================
// HOLIDAYS & TIME UTILITIES
// =============================================================================

function getDateForDay(dayIndex) {
    const weekStart = new Date(State.currentWeekStart);
    const wed = new Date(weekStart);
    wed.setDate(wed.getDate() + 2 + dayIndex);
    return wed.toISOString().split('T')[0];
}

function getHolidayForDay(dayIndex) {
    return holidays[getDateForDay(dayIndex)] || null;
}

function formatTime(time) {
    if (!time || time === '-') return time;
    return time;
}

function parseTimeInput(value) {
    if (!value || value.trim() === '') return null;
    
    value = value.trim().toUpperCase();
    
    if (value === '-' || value === 'OFF') return '-';
    if (value === 'CLOSE' || value === 'CL') return 'CLOSE';
    if (value === 'CLOSED') return 'CLOSED';
    
    const match = value.match(/^(\d{1,2})(?::(\d{2}))?\s*(A|AM|P|PM)?$/i);
    if (!match) return value;
    
    let hours = parseInt(match[1]);
    let mins = match[2] ? parseInt(match[2]) : 0;
    let period = match[3] ? match[3].charAt(0).toUpperCase() : null;
    
    if (!period) {
        if (hours >= 6 && hours <= 11) period = 'A';
        else if (hours === 12) period = 'P';
        else if (hours >= 1 && hours <= 5) period = 'P';
        else period = 'A';
    }
    
    const displayHour = hours === 0 ? 12 : (hours > 12 ? hours - 12 : hours);
    const ampm = period === 'A' ? 'AM' : 'PM';
    return `${displayHour}:${mins.toString().padStart(2, '0')} ${ampm}`;
}

function parseTimeToMinutes(timeStr) {
    if (!timeStr || timeStr === '-') return null;
    
    const match = timeStr.match(/(\d{1,2}):(\d{2})\s*(AM|PM)/i);
    if (!match) return null;
    
    let hours = parseInt(match[1]);
    const minutes = parseInt(match[2]);
    const period = match[3].toUpperCase();
    
    if (period === 'PM' && hours !== 12) hours += 12;
    if (period === 'AM' && hours === 12) hours = 0;
    
    return hours * 60 + minutes;
}

function calculateWeeklyHours(shifts) {
    let total = 0;
    
    shifts.forEach((shift, dayIndex) => {
        if (!shift || shift.in === '-' || !shift.in || !shift.out) return;
        
        const inTime = parseTimeToMinutes(shift.in);
        let outTime = parseTimeToMinutes(shift.out);
        
        if (shift.out === 'CLOSE') {
            const officeClose = scheduleData.officeHours[dayIndex]?.out;
            outTime = parseTimeToMinutes(officeClose) || parseTimeToMinutes('10:00 PM');
        }
        
        if (inTime !== null && outTime !== null && outTime > inTime) {
            total += (outTime - inTime) / 60;
        }
    });
    
    return total;
}

function generateTimeOptions(selectedTime) {
    const times = [];
    for (let h = 6; h <= 22; h++) {
        for (let m = 0; m < 60; m += 30) {
            const hour = h > 12 ? h - 12 : (h === 0 ? 12 : h);
            const period = h >= 12 ? 'PM' : 'AM';
            const time = `${hour}:${m.toString().padStart(2, '0')} ${period}`;
            const selected = time === selectedTime ? 'selected' : '';
            times.push(`<option value="${time}" ${selected}>${time}</option>`);
        }
    }
    return times.join('');
}

// =============================================================================
// EXPORT FUNCTIONS
// =============================================================================

function exportToExcel() {
    window.location.href = `${Config.API_BASE}/api/schedule/${State.currentWeekStart}/export`;
}

function exportToPDF() {
    document.body.classList.add('pdf-export');
    
    const coverageContainer = document.getElementById('coverageContainer');
    const wasShowingCoverage = coverageContainer && coverageContainer.style.display !== 'none';
    if (wasShowingCoverage) coverageContainer.style.display = 'none';
    
    window.print();
    
    document.body.classList.remove('pdf-export');
    if (wasShowingCoverage) coverageContainer.style.display = 'block';
}

// =============================================================================
// EVENT LISTENERS
// =============================================================================

function setupEventListeners() {
    setupTabNavigation();
    setupDragAndDrop();
}

function setupTabNavigation() {
    document.querySelectorAll('.shift-input').forEach(input => {
        input.addEventListener('keydown', function(e) {
            const allInputs = Array.from(document.querySelectorAll('.shift-input'));
            const currentIndex = allInputs.indexOf(this);
            
            if (e.key === 'Tab') {
                e.preventDefault();
                let nextIndex = e.shiftKey ? currentIndex - 1 : currentIndex + 1;
                if (nextIndex < 0) nextIndex = allInputs.length - 1;
                if (nextIndex >= allInputs.length) nextIndex = 0;
                allInputs[nextIndex].focus();
                allInputs[nextIndex].select();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                this.blur();
                const nextIndex = currentIndex + 14;
                if (nextIndex < allInputs.length) {
                    allInputs[nextIndex].focus();
                    allInputs[nextIndex].select();
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextIndex = currentIndex + 14;
                if (nextIndex < allInputs.length) {
                    allInputs[nextIndex].focus();
                    allInputs[nextIndex].select();
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const nextIndex = currentIndex - 14;
                if (nextIndex >= 0) {
                    allInputs[nextIndex].focus();
                    allInputs[nextIndex].select();
                }
            } else if (e.key === 'ArrowRight' && this.selectionStart === this.value.length) {
                e.preventDefault();
                if (currentIndex + 1 < allInputs.length) {
                    allInputs[currentIndex + 1].focus();
                    allInputs[currentIndex + 1].select();
                }
            } else if (e.key === 'ArrowLeft' && this.selectionStart === 0) {
                e.preventDefault();
                if (currentIndex - 1 >= 0) {
                    allInputs[currentIndex - 1].focus();
                    allInputs[currentIndex - 1].select();
                }
            }
        });
    });
}

// =============================================================================
// DRAG AND DROP
// =============================================================================

let draggedRow = null;
let draggedIndex = null;

function setupDragAndDrop() {
    const staffRows = document.querySelectorAll('.employee-row.staff[draggable="true"]');
    
    staffRows.forEach(row => {
        row.addEventListener('dragstart', handleDragStart);
        row.addEventListener('dragend', handleDragEnd);
        row.addEventListener('dragover', handleDragOver);
        row.addEventListener('dragenter', handleDragEnter);
        row.addEventListener('dragleave', handleDragLeave);
        row.addEventListener('drop', handleDrop);
    });
}

function handleDragStart(e) {
    if (State.currentView === 'employee') {
        e.preventDefault();
        return;
    }
    
    draggedRow = this;
    draggedIndex = parseInt(this.dataset.index);
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', draggedIndex);
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    draggedRow = null;
    draggedIndex = null;
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
    e.preventDefault();
    if (this !== draggedRow && this.classList.contains('staff')) {
        this.classList.add('drag-over');
    }
}

function handleDragLeave(e) {
    this.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    
    if (this === draggedRow) return;
    
    const targetIndex = parseInt(this.dataset.index);
    if (draggedIndex === targetIndex) return;
    
    saveStateForUndo();
    
    const [movedEmployee] = scheduleData.employees.splice(draggedIndex, 1);
    scheduleData.employees.splice(targetIndex, 0, movedEmployee);
    
    updateEmployeeOrder();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

async function updateEmployeeOrder() {
    for (let i = 0; i < scheduleData.employees.length; i++) {
        const emp = scheduleData.employees[i];
        try {
            await fetch(`${Config.API_BASE}/api/employees/${emp.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sort_order: i + 1 })
            });
        } catch (error) {
            console.error('Error updating employee order:', error);
        }
    }
}

// =============================================================================
// SHIFT EDITING
// =============================================================================

function handleShiftInput(input, section, empIndex, dayIndex, type) {
    saveStateForUndo();
    
    const value = parseTimeInput(input.value);
    
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    if (!employee.shifts[dayIndex]) {
        employee.shifts[dayIndex] = { in: null, out: null };
    }
    
    employee.shifts[dayIndex][type] = value;
    
    if (!employee.shifts[dayIndex].in && !employee.shifts[dayIndex].out) {
        employee.shifts[dayIndex] = null;
    }
    
    input.value = value || '';
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

function updateShiftData(section, empIndex, dayIndex, shiftData) {
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    employee.shifts[dayIndex] = shiftData;
}

// =============================================================================
// MODALS
// =============================================================================

function closeModal() {
    ['editModal', 'noteModal', 'employeeModal', 'officeHoursModal', 'eventsModal'].forEach(id => {
        const modal = document.getElementById(id);
        if (modal) modal.remove();
    });
    State.currentEdit = null;
}

function openShiftModal(section, empIndex, dayIndex) {
    if (State.currentView === 'employee') return;
    
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    const day = scheduleData.days[dayIndex];
    const shift = employee.shifts[dayIndex];
    State.currentEdit = { section, empIndex, dayIndex, employee };
    
    const inTime = shift && shift.in !== '-' ? shift.in : '';
    const outTime = shift && shift.out !== '-' ? shift.out : '';
    
    const templateBtns = shiftTemplates.map(t =>
        `<button class="template-btn" onclick="applyTemplate('${t.in}', '${t.out}')">${t.name}</button>`
    ).join('');
    
    const modalHtml = `
        <div class="modal-overlay active" id="editModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Edit Shift</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-employee">${employee.name}</div>
                    <div class="modal-day">${day.name}, ${day.date}</div>
                    
                    <div class="quick-actions">
                        <button class="quick-btn off" onclick="setOff()">Mark as Off</button>
                        <button class="quick-btn" onclick="clearShift()">Clear</button>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label>In Time</label>
                            <select id="inTime">
                                <option value="">-- Select --</option>
                                ${generateTimeOptions(inTime)}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Out Time</label>
                            <select id="outTime">
                                <option value="">-- Select --</option>
                                ${generateTimeOptions(outTime)}
                                <option value="CLOSE" ${outTime === 'CLOSE' ? 'selected' : ''}>CLOSE</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="shift-templates">
                        <div class="shift-templates-label">Quick Templates:</div>
                        ${templateBtns}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveShift()">Save</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function applyTemplate(inTime, outTime) {
    document.getElementById('inTime').value = inTime;
    document.getElementById('outTime').value = outTime;
}

function setOff() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    const { section, empIndex, dayIndex } = State.currentEdit;
    updateShiftData(section, empIndex, dayIndex, { in: '-', out: '-' });
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

function clearShift() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    const { section, empIndex, dayIndex } = State.currentEdit;
    updateShiftData(section, empIndex, dayIndex, null);
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

function saveShift() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    const { section, empIndex, dayIndex } = State.currentEdit;
    
    const inTime = document.getElementById('inTime').value;
    const outTime = document.getElementById('outTime').value;
    
    if (inTime || outTime) {
        updateShiftData(section, empIndex, dayIndex, { in: inTime, out: outTime });
    } else {
        updateShiftData(section, empIndex, dayIndex, null);
    }
    
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

// =============================================================================
// EMPLOYEE MANAGEMENT
// =============================================================================

function openAddEmployeeModal() {
    const modalHtml = `
        <div class="modal-overlay active" id="employeeModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Add Employee</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Name</label>
                        <input type="text" id="empName" placeholder="Employee name">
                    </div>
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" id="empPhone" placeholder="(XXX) XXX-XXXX">
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveNewEmployee()">Add</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    document.getElementById('empName').focus();
}

async function saveNewEmployee() {
    const name = document.getElementById('empName').value.trim();
    const phone = document.getElementById('empPhone').value.trim();
    
    if (!name) {
        alert('Please enter a name');
        return;
    }
    
    try {
        const response = await fetch(`${Config.API_BASE}/api/employees`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, phone, section: 'staff' })
        });
        
        if (!response.ok) throw new Error('Failed to add employee');
        
        const newEmp = await response.json();
        
        scheduleData.employees.push({
            id: newEmp.id,
            name: newEmp.name,
            phone: newEmp.phone || '',
            shifts: [null, null, null, null, null, null, null],
            note: ''
        });
        
        closeModal();
        renderSchedule();
        setupEventListeners();
    } catch (error) {
        console.error('Error adding employee:', error);
        alert('Failed to add employee');
    }
}

function openEmployeeModal(section, empIndex) {
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    const modalHtml = `
        <div class="modal-overlay active" id="employeeModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Edit Employee</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Name</label>
                        <input type="text" id="empName" value="${employee.name}">
                    </div>
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" id="empPhone" value="${employee.phone || ''}">
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveEmployee('${section}', ${empIndex})">Save</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function saveEmployee(section, empIndex) {
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    const name = document.getElementById('empName').value.trim();
    const phone = document.getElementById('empPhone').value.trim();
    
    if (!name) {
        alert('Please enter a name');
        return;
    }
    
    try {
        await fetch(`${Config.API_BASE}/api/employees/${employee.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, phone })
        });
        
        employee.name = name;
        employee.phone = phone;
        
        closeModal();
        renderSchedule();
        setupEventListeners();
    } catch (error) {
        console.error('Error updating employee:', error);
        alert('Failed to update employee');
    }
}

async function deleteEmployee(empIndex) {
    const emp = scheduleData.employees[empIndex];
    
    if (!confirm(`Delete ${emp.name}?`)) return;
    
    try {
        await fetch(`${Config.API_BASE}/api/employees/${emp.id}`, {
            method: 'DELETE'
        });
        
        scheduleData.employees.splice(empIndex, 1);
        renderSchedule();
        setupEventListeners();
    } catch (error) {
        console.error('Error deleting employee:', error);
        alert('Failed to delete employee');
    }
}

// =============================================================================
// EMPLOYEE NOTES
// =============================================================================

function openNoteModal(section, empIndex) {
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    const currentNote = employee.note || '';
    
    const modalHtml = `
        <div class="modal-overlay active" id="noteModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Employee Note</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-employee">${employee.name}</div>
                    <div class="modal-day">Week of ${scheduleData.weekTitle}</div>
                    
                    <div class="form-group" style="margin-top: 16px;">
                        <label>Note (e.g., availability, school schedule)</label>
                        <textarea id="employeeNote" rows="4" style="width: 100%;" placeholder="Finals week - limited availability...">${currentNote}</textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveNote('${section}', ${empIndex})">Save</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function saveNote(section, empIndex) {
    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }
    
    const note = document.getElementById('employeeNote').value.trim();
    
    try {
        await fetch(`${Config.API_BASE}/api/notes/${State.currentWeekStart}/${employee.id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note })
        });
        
        employee.note = note;
        
        closeModal();
        renderSchedule();
        setupEventListeners();
    } catch (error) {
        console.error('Error saving note:', error);
        alert('Failed to save note');
    }
}

// =============================================================================
// OFFICE HOURS
// =============================================================================

function openOfficeHoursModal(dayIndex) {
    if (State.currentView === 'employee') return;
    
    const day = scheduleData.days[dayIndex];
    const hours = scheduleData.officeHours[dayIndex];
    State.currentEdit = { type: 'officeHours', dayIndex };
    
    const modalHtml = `
        <div class="modal-overlay active" id="officeHoursModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Office Hours</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-day">${day.name}, ${day.date}</div>
                    
                    <div class="quick-actions">
                        <button class="quick-btn off" onclick="setOfficeClosed()">Mark as CLOSED</button>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label>Open</label>
                            <select id="ohOpen">
                                <option value="">-- Select --</option>
                                ${generateTimeOptions(hours.in)}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Close</label>
                            <select id="ohClose">
                                <option value="">-- Select --</option>
                                ${generateTimeOptions(hours.out)}
                            </select>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveOfficeHours()">Save</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function setOfficeClosed() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    scheduleData.officeHours[State.currentEdit.dayIndex] = { in: 'CLOSED', out: '' };
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

function handleOfficeHoursInput(input, dayIndex, type) {
    saveStateForUndo();
    
    const value = parseTimeInput(input.value);
    
    if (!scheduleData.officeHours[dayIndex]) {
        scheduleData.officeHours[dayIndex] = { in: '', out: '' };
    }
    
    scheduleData.officeHours[dayIndex][type] = value;
    input.value = value || '';
    
    markUnsaved();
}

function saveOfficeHours() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    
    const openTime = document.getElementById('ohOpen').value;
    const closeTime = document.getElementById('ohClose').value;
    scheduleData.officeHours[State.currentEdit.dayIndex] = { in: openTime, out: closeTime };
    
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

// =============================================================================
// EVENTS
// =============================================================================

function openEventsModal(dayIndex) {
    if (State.currentView === 'employee') return;
    
    const day = scheduleData.days[dayIndex];
    const events = scheduleData.events[dayIndex] || [];
    State.currentEdit = { type: 'events', dayIndex };
    
    const modalHtml = `
        <div class="modal-overlay active" id="eventsModal">
            <div class="modal">
                <div class="modal-header">
                    <h3>Special Events</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-day">${day.name}, ${day.date}</div>
                    
                    <div class="form-group" style="margin-top: 16px;">
                        <label>Events (one per line)</label>
                        <textarea id="eventsText" rows="4" style="width: 100%;" placeholder="Tournament&#10;Special Event">${events.join('\n')}</textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-save" onclick="saveEvents()">Save</button>
                </div>
            </div>
        </div>
    `;
    
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function saveEvents() {
    if (!State.currentEdit) return;
    saveStateForUndo();
    
    const text = document.getElementById('eventsText').value;
    const events = text.split('\n').map(e => e.trim()).filter(e => e);
    scheduleData.events[State.currentEdit.dayIndex] = events;
    
    closeModal();
    markUnsaved();
    renderSchedule();
    setupEventListeners();
}

function handleEventInput(input, dayIndex) {
    saveStateForUndo();
    
    const value = input.value.trim();
    // Split by comma for multiple events, or treat as single event
    const events = value ? value.split(',').map(e => e.trim()).filter(e => e) : [];
    
    scheduleData.events[dayIndex] = events;
    
    markUnsaved();
}

// =============================================================================
// RENDER FUNCTIONS
// =============================================================================

function renderSchedule() {
    const app = document.getElementById('app');
    const isDark = document.body.classList.contains('dark-mode');
    
    app.innerHTML = `
        <div class="app-header">
            <img src="/static/Ice_Line_Logo.png" alt="Ice Line" class="logo">
            <span class="app-title">Employee Scheduler</span>
        </div>
        ${renderToolbar()}
        <div class="schedule-container">
            <table class="schedule-table">
                ${renderTitleRow()}
                ${renderDayHeaderRow()}
                ${renderInOutHeaderRow()}
                ${renderEmployeeRows()}
                ${renderSectionDivider()}
                ${renderOfficeHoursRow()}
                ${renderNoticeRow()}
                ${renderEventsRow()}
            </table>
            <div class="view-indicator">Employee Schedule View</div>
        </div>
        ${renderLegend()}
        <div class="coverage-container" id="coverageContainer" style="display: none;"></div>
    `;
    
    const darkBtn = document.querySelector('.dark-mode-toggle');
    if (darkBtn) darkBtn.textContent = isDark ? '☀️' : '🌙';
    
    setView(State.currentView);
    updateUndoRedoButtons();
}

function renderToolbar() {
    return `
        <div class="toolbar">
            <div class="toolbar-left">
                <div class="week-nav">
                    <button class="week-nav-btn" onclick="navigateWeek(-1)" title="Previous Week">◀</button>
                    <span class="week-display">Week of ${scheduleData.weekTitle}</span>
                    <button class="week-nav-btn" onclick="navigateWeek(1)" title="Next Week">▶</button>
                </div>
                <button class="action-btn" onclick="copyPreviousWeek()">
                    <span class="icon">📋</span> Copy Previous Week
                </button>
                <div class="undo-redo-btns">
                    <button class="undo-redo-btn" onclick="undo()" title="Undo (Ctrl+Z)" id="undoBtn" disabled>↶</button>
                    <button class="undo-redo-btn" onclick="redo()" title="Redo (Ctrl+Y)" id="redoBtn" disabled>↷</button>
                </div>
                <span class="auto-save-status" id="autoSaveStatus">
                    <span class="icon">✓</span> Auto-saved
                </span>
                <div class="keyboard-hints">
                    <span class="keyboard-hint"><kbd>Tab</kbd> next cell</span>
                    <span class="keyboard-hint"><kbd>Enter</kbd> next row</span>
                    <span class="keyboard-hint"><kbd>↑↓</kbd> navigate</span>
                </div>
            </div>
            <div class="toolbar-right">
                <div class="backup-dropdown">
                    <button class="action-btn" onclick="toggleBackupMenu()">
                        <span class="icon">💾</span> Backup
                    </button>
                    <div class="backup-menu" id="backupMenu">
                        <button onclick="exportBackup()">📥 Export JSON Backup</button>
                        <button onclick="triggerImport()">📤 Import from Backup</button>
                        <input type="file" id="importFileInput" accept=".json" style="display:none" onchange="importBackup(this)">
                    </div>
                </div>
                <button class="action-btn" onclick="exportToExcel()">
                    <span class="icon">📊</span> Export Excel
                </button>
                <button class="action-btn" onclick="exportToPDF()">
                    <span class="icon">📄</span> PDF
                </button>
                <button class="action-btn" onclick="window.print()">
                    <span class="icon">🖨️</span> Print
                </button>
                <button class="action-btn" onclick="toggleCoverage()">
                    <span class="icon">📈</span> Coverage
                </button>
                <button class="dark-mode-toggle" onclick="toggleDarkMode()" title="Toggle dark mode">🌙</button>
                <span class="view-label">View:</span>
                <div class="view-toggle">
                    <button class="view-btn active" data-view="manager" onclick="setView('manager')">Manager</button>
                    <button class="view-btn" data-view="employee" onclick="setView('employee')">Employee</button>
                </div>
            </div>
        </div>
    `;
}

function renderTitleRow() {
    return `
        <tr class="title-row">
            <td colspan="16">Ice Line Office Schedule — Week of ${scheduleData.weekTitle}</td>
        </tr>
    `;
}

function renderDayHeaderRow() {
    let html = '<tr class="day-header-row"><th>Employee</th>';
    
    scheduleData.days.forEach((day, dayIndex) => {
        const weekendClass = day.isWeekend ? 'weekend' : '';
        const holiday = getHolidayForDay(dayIndex);
        const holidayClass = holiday ? 'holiday' : '';
        const holidayHtml = holiday ? `<div class="holiday-indicator">🎉 ${holiday}</div>` : '';
        
        html += `
            <th colspan="2" class="${weekendClass} ${holidayClass}">
                <div class="day-name">${day.name}</div>
                <div class="day-date">${day.date}</div>
                ${holidayHtml}
            </th>
        `;
    });
    
    html += '<th class="hours-header">Hours</th></tr>';
    return html;
}

function renderInOutHeaderRow() {
    let html = '<tr class="inout-header-row"><th></th>';
    
    scheduleData.days.forEach(day => {
        const weekendClass = day.isWeekend ? 'weekend' : '';
        html += `<th class="${weekendClass}">In</th><th class="${weekendClass}">Out</th>`;
    });
    
    html += '<th class="hours-header"></th></tr>';
    return html;
}

function renderEmployeeRows() {
    let html = '';
    
    // Managers
    scheduleData.managers.forEach((emp, i) => {
        html += renderSingleEmployeeRow(emp, 'manager', i);
    });
    
    html += '<tr class="section-divider"><td colspan="16"></td></tr>';
    
    // Zak
    if (scheduleData.zakReilly) {
        html += renderSingleEmployeeRow(scheduleData.zakReilly, 'zak', 0);
    }
    
    html += '<tr class="section-divider"><td colspan="16"></td></tr>';
    
    // Staff
    scheduleData.employees.forEach((emp, i) => {
        html += renderSingleEmployeeRow(emp, 'staff', i);
    });
    
    // Add employee row
    html += `
        <tr class="add-employee-row" onclick="openAddEmployeeModal()">
            <td colspan="16">
                <span class="add-btn">+ Add Employee</span>
            </td>
        </tr>
    `;
    
    return html;
}

function renderSingleEmployeeRow(emp, section, empIndex) {
    const draggable = section === 'staff' ? 'draggable="true"' : '';
    let html = `<tr class="employee-row ${section}" ${draggable} data-section="${section}" data-index="${empIndex}">`;
    
    const hasNote = emp.note;
    const noteClass = hasNote ? 'has-note' : '';
    const noteTitle = hasNote || 'Add note';
    
    html += `
        <td>
            ${section === 'staff' ? '<span class="drag-handle" title="Drag to reorder">☰</span>' : ''}
            <span class="employee-name">${emp.name}</span>
            ${emp.phone ? `<span class="employee-phone">${emp.phone}</span>` : ''}
            <span class="employee-note-icon ${noteClass}" onclick="openNoteModal('${section}', ${empIndex})" title="${noteTitle}">📝</span>
            <div class="employee-actions">
                <button class="emp-action-btn edit" onclick="openEmployeeModal('${section}', ${empIndex})" title="Edit">✎</button>
                ${section === 'staff' ? `<button class="emp-action-btn delete" onclick="deleteEmployee(${empIndex})" title="Delete">✕</button>` : ''}
            </div>
        </td>
    `;
    
    // Shifts for each day
    emp.shifts.forEach((shift, dayIndex) => {
        const isWeekend = scheduleData.days[dayIndex].isWeekend;
        const weekendClass = isWeekend ? 'weekend' : '';
        
        const inVal = shift ? (shift.in === '-' ? '-' : formatTime(shift.in) || '') : '';
        const outVal = shift ? (shift.out === '-' ? '-' : formatTime(shift.out) || '') : '';
        
        html += `<td class="shift-cell ${weekendClass}" data-section="${section}" data-emp="${empIndex}" data-day="${dayIndex}" data-type="in">
            <input type="text" class="shift-input" value="${inVal}" 
                   onchange="handleShiftInput(this, '${section}', ${empIndex}, ${dayIndex}, 'in')"
                   onclick="event.stopPropagation()"
                   placeholder="—">
            <button class="shift-popup-btn" onclick="openShiftModal('${section}', ${empIndex}, ${dayIndex})" title="More options">⚙</button>
        </td>`;
        
        html += `<td class="shift-cell ${weekendClass}" data-section="${section}" data-emp="${empIndex}" data-day="${dayIndex}" data-type="out">
            <input type="text" class="shift-input" value="${outVal}"
                   onchange="handleShiftInput(this, '${section}', ${empIndex}, ${dayIndex}, 'out')"
                   onclick="event.stopPropagation()"
                   placeholder="—">
        </td>`;
    });
    
    // Hours column
    const totalHours = calculateWeeklyHours(emp.shifts);
    const overtimeClass = totalHours > Config.OVERTIME_THRESHOLD ? 'overtime' : '';
    html += `<td class="hours-cell ${overtimeClass}">${totalHours > 0 ? totalHours.toFixed(1) : '-'}</td>`;
    
    html += '</tr>';
    return html;
}

function renderSectionDivider() {
    return '<tr class="section-divider"><td colspan="16"></td></tr>';
}

function renderOfficeHoursRow() {
    let html = '<tr class="office-hours-row">';
    html += '<td>Front Office Hours*</td>';
    
    scheduleData.officeHours.forEach((hours, dayIndex) => {
        const isWeekend = scheduleData.days[dayIndex].isWeekend;
        const weekendClass = isWeekend ? 'weekend' : '';
        
        if (hours.in === 'CLOSED') {
            html += `<td colspan="2" class="${weekendClass}" onclick="openOfficeHoursModal(${dayIndex})">CLOSED</td>`;
        } else {
            html += `<td class="shift-cell ${weekendClass}">
                <input type="text" class="shift-input" value="${hours.in || ''}" 
                       onchange="handleOfficeHoursInput(this, ${dayIndex}, 'in')"
                       onclick="event.stopPropagation()"
                       placeholder="—">
                <button class="shift-popup-btn" onclick="openOfficeHoursModal(${dayIndex})" title="More options">⚙</button>
            </td>`;
            html += `<td class="shift-cell ${weekendClass}">
                <input type="text" class="shift-input" value="${hours.out || ''}" 
                       onchange="handleOfficeHoursInput(this, ${dayIndex}, 'out')"
                       onclick="event.stopPropagation()"
                       placeholder="—">
            </td>`;
        }
    });
    
    html += '<td class="hours-cell"></td></tr>';
    return html;
}

function renderNoticeRow() {
    return `
        <tr class="notice-row">
            <td>* Hours are subject to change</td>
            <td colspan="14" class="warning">IF UNABLE TO WORK A SCHEDULED SHIFT YOU MUST FIND A REPLACEMENT</td>
        </tr>
    `;
}

function renderEventsRow() {
    let html = '<tr class="events-row">';
    html += '<td>Special Events:</td>';
    
    scheduleData.events.forEach((events, dayIndex) => {
        const isWeekend = scheduleData.days[dayIndex].isWeekend;
        const weekendClass = isWeekend ? 'weekend' : '';
        const eventText = events && events.length > 0 ? events.join(', ') : '';
        
        html += `<td colspan="2" class="shift-cell ${weekendClass}" onclick="openEventsModal(${dayIndex})" style="cursor: pointer;">
            <span class="event-text">${eventText}</span>
        </td>`;
    });
    
    html += '<td class="hours-cell"></td></tr>';
    return html;
}

function renderLegend() {
    return `
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color manager"></div>
                <span>Managers</span>
            </div>
            <div class="legend-item">
                <div class="legend-color zak"></div>
                <span>Zak Reilly</span>
            </div>
            <div class="legend-item">
                <div class="legend-color staff"></div>
                <span>Staff</span>
            </div>
            <div class="legend-item">
                <div class="legend-color weekend"></div>
                <span>Weekend</span>
            </div>
        </div>
    `;
}

function renderCoverageView() {
    const hours = [];
    for (let h = 6; h <= 22; h++) {
        const displayHour = h > 12 ? h - 12 : h;
        const period = h >= 12 ? 'PM' : 'AM';
        hours.push(`${displayHour} ${period}`);
    }
    
    let html = '<div class="coverage-header"><h3>Coverage View</h3></div>';
    html += '<div class="coverage-grid">';
    
    // Header row
    html += '<div class="coverage-cell header">Time</div>';
    scheduleData.days.forEach(day => {
        html += `<div class="coverage-cell header">${day.name}</div>`;
    });
    
    // Time rows
    hours.forEach(hour => {
        html += `<div class="coverage-cell time-label">${hour}</div>`;
        scheduleData.days.forEach((day, dayIndex) => {
            const count = countStaffAtHour(dayIndex, hour);
            const levelClass = `level-${Math.min(count, 5)}`;
            html += `<div class="coverage-cell ${levelClass}">${count}</div>`;
        });
    });
    
    html += '</div>';
    return html;
}

function countStaffAtHour(dayIndex, hourStr) {
    const [hour, period] = hourStr.split(' ');
    let hourNum = parseInt(hour);
    if (period === 'PM' && hourNum !== 12) hourNum += 12;
    if (period === 'AM' && hourNum === 12) hourNum = 0;
    
    const checkMinutes = hourNum * 60;
    let count = 0;
    
    const allEmployees = [
        ...scheduleData.managers,
        scheduleData.zakReilly,
        ...scheduleData.employees
    ].filter(e => e);
    
    allEmployees.forEach(emp => {
        const shift = emp.shifts[dayIndex];
        if (!shift || shift.in === '-' || !shift.in) return;
        
        const inMinutes = parseTimeToMinutes(shift.in);
        let outMinutes = parseTimeToMinutes(shift.out);
        
        if (shift.out === 'CLOSE') {
            const officeClose = scheduleData.officeHours[dayIndex]?.out;
            outMinutes = parseTimeToMinutes(officeClose) || parseTimeToMinutes('10:00 PM');
        }
        
        if (inMinutes !== null && outMinutes !== null) {
            if (checkMinutes >= inMinutes && checkMinutes < outMinutes) {
                count++;
            }
        }
    });
    
    return count;
}
