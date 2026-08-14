from datetime import datetime, timedelta
from html import escape

import streamlit as st


ROLE_HOME_COPY = {
    "Developer": ("System-wide access", "Everything across Planet Bark is available from here."),
    "Boss": ("Facility overview", "Keep the day moving and step into any team when needed."),
    "Office": ("Front desk companion", "Stay ahead of arrivals, records, assignments, and departures."),
    "Cross-Trained": ("Flexible team companion", "Move between the floor and front desk without losing context."),
    "Crew": ("Crew companion", "Your shift, care tasks, schedule, and dog operations in one place."),
}


def day_phase(now=None):
    now = now or datetime.now()
    hour = now.hour
    if hour < 9:
        return "Opening & arrivals", "Start strong: review staffing, arrivals, and first priorities."
    if hour < 12:
        return "Morning operations", "Keep rooms, front desk, and care tasks moving together."
    if hour < 14:
        return "Midday & nap time", "Focus on transitions, placements, meals, and medication checks."
    if hour < 17:
        return "Afternoon operations", "Prepare departures while keeping care work on track."
    return "Closing & handoff", "Finish outstanding work and leave a clear handoff for the team."


def crew_right_now(my_shifts, today, now=None):
    """Return schedule-aware copy for the Crew briefing."""
    now = now or datetime.now()
    hour = now.hour

    if hour >= 19 or hour < 5:
        return "Crickets…", "🦗 🦗 🦗"

    today_rows = (
        my_shifts[my_shifts["starts_at"].dt.date == today]
        if not my_shifts.empty else my_shifts
    )
    if today_rows.empty:
        weekday = today.strftime("%A")
        return f"Enjoy your {weekday} off", "We’ll see you on your next shift."

    starts = today_rows["starts_at"].min()
    ends = today_rows["ends_at"].max()
    has_am = bool((today_rows["starts_at"].dt.hour < 12).any())
    has_pm = bool((today_rows["starts_at"].dt.hour >= 12).any())

    if has_pm and not has_am and now < starts:
        return "See you later!", "Enjoy your morning—we’ll see you for your PM shift."

    if has_am and not has_pm and now >= ends:
        if hour < 17:
            return "Enjoy your afternoon", "Your shift is complete. Have a great afternoon!"
        return "Enjoy your evening", "Your shift is complete. Have a great evening!"

    return day_phase(now)


def crew_team_day(today, now=None):
    """Show tomorrow's staffing after 7 PM; otherwise show today's."""
    now = now or datetime.now()
    if now.hour >= 19:
        return today + timedelta(days=1), "Tomorrow’s team", "tomorrow"
    return today, "Today’s team", "today"


def shift_summary(my_shifts, today):
    if my_shifts.empty:
        return "No shift posted", "Check Schedule for upcoming hours"
    today_rows = my_shifts[my_shifts["starts_at"].dt.date == today]
    if today_rows.empty:
        return "Not scheduled today", "Your next shift is available in Schedule"
    row = today_rows.iloc[0]
    hours = (
        f"{row['starts_at'].strftime('%I:%M %p').lstrip('0')}–"
        f"{row['ends_at'].strftime('%I:%M %p').lstrip('0')}"
    )
    return hours, str(row.get("department") or "Planet Bark")


def show_companion_hero(user, shift_value, shift_detail, phase_title, phase_detail):
    role = str(user["role"])
    eyebrow, role_copy = ROLE_HOME_COPY.get(role, ("Staff companion", "Your day at Planet Bark."))
    first_name = escape(str(user.get("display_name") or "Employee").strip().split()[0])
    st.markdown(
        f"""
        <section class="companion-hero">
            <div class="companion-hero-copy">
                <span class="companion-eyebrow">{escape(eyebrow)}</span>
                <h1>Good day, {first_name}</h1>
                <p>{escape(role_copy)}</p>
            </div>
            <div class="companion-shift-card">
                <span>MY SHIFT</span>
                <strong>{escape(shift_value)}</strong>
                <small>{escape(shift_detail)}</small>
            </div>
        </section>
        <section class="companion-now">
            <span class="companion-now-dot"></span>
            <div><small>RIGHT NOW</small><strong>{escape(phase_title)}</strong></div>
            <p>{escape(phase_detail)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def show_crew_briefing_header(user, shift_value, shift_detail, phase_title, phase_detail):
    first_name = escape(str(user.get("display_name") or "Employee").strip().split()[0])
    now_text = datetime.now().strftime("%I:%M %p").lstrip("0")
    phase_lower = phase_title.casefold()
    if "cricket" in phase_lower:
        phase_tone = "night"
    elif "off" in phase_lower:
        phase_tone = "off"
    elif "see you" in phase_lower:
        phase_tone = "upcoming"
    elif "enjoy" in phase_lower:
        phase_tone = "complete"
    else:
        phase_tone = "working"
    st.markdown(
        f"""
        <span class="crew-mode-marker" aria-hidden="true"></span>
        <header class="crew-briefing-header">
            <div>
                <span class="crew-kicker">CREW COMPANION</span>
                <h1>{first_name}</h1>
                <p>{escape(shift_detail)} <span aria-hidden="true">&middot;</span> {escape(shift_value)}</p>
            </div>
            <time>{escape(now_text)}</time>
        </header>
        <section class="crew-now-line crew-now-line--{phase_tone}">
            <span>RIGHT NOW</span>
            <strong>{escape(phase_title)}</strong>
            <p>{escape(phase_detail)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def show_office_front_desk_header(user, shift_value, shift_detail, present_count,
                                  arrival_count, departure_count):
    first_name = escape(str(user.get("display_name") or "Employee").strip().split()[0])
    now = datetime.now()
    st.markdown(
        f"""
        <header class="office-front-header">
            <div>
                <span class="office-kicker">FRONT DESK</span>
                <h1>Good day, {first_name}</h1>
                <p>{escape(shift_detail)} <span aria-hidden="true">&middot;</span> {escape(shift_value)}</p>
            </div>
            <div class="office-date-block">
                <strong>{escape(now.strftime('%A'))}</strong>
                <span>{escape(now.strftime('%m/%d/%Y'))}</span>
                <time>{escape(now.strftime('%I:%M %p').lstrip('0'))}</time>
            </div>
        </header>
        <section class="office-pulse-strip">
            <div><strong>{int(present_count)}</strong><span>Present</span></div>
            <div><strong>{int(arrival_count)}</strong><span>Arrivals</span></div>
            <div><strong>{int(departure_count)}</strong><span>Departures</span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def navigate_button(column, label, page, key, *, primary=False):
    if column.button(
        label,
        key=key,
        type="primary" if primary else "secondary",
        use_container_width=True,
    ):
        st.session_state.page = page
        st.rerun()
