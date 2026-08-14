from datetime import date, datetime, time, timedelta
from html import escape

import pandas as pd
import streamlit as st

from auth import ROLES, create_user, current_user, has_section, uses_password
from components.companion import (
    crew_right_now, crew_team_day, day_phase, navigate_button, shift_summary, show_companion_hero,
    show_crew_briefing_header, show_office_front_desk_header,
)
from database import load_all_dogs, load_dogs
from views.dashboard import show_dashboard_clock_and_weather
from operations_service import (
    clear_generated_shifts, create_shift, create_shifts_batch, create_task,
    create_detailed_time_off_request, create_shift_trade_request,
    create_time_off_request, delete_user,
    load_audit, load_day_summary,
    is_schedule_holiday, load_normal_schedule, load_shifts, load_tasks, load_users,
    load_shift_trade_requests, load_time_off_request_days,
    load_time_off_requests, remove_shift,
    review_shift_trade_request, review_time_off_request,
    save_normal_schedule, set_schedule_holiday, set_user_access,
    update_task_status, update_user_account,
)


SHIFT_PRESETS = {
    "Crew AM — 6:45 AM–12:00 PM": (time(6, 45), time(12, 0), "Crew"),
    "Back Up AM — 8:00 AM–11:30 AM": (time(8, 0), time(11, 30), "Crew"),
    "Crew PM — 2:00 PM–7:00 PM": (time(14, 0), time(19, 0), "Crew"),
    "Back Up PM — 2:00 PM–5:00 PM": (time(14, 0), time(17, 0), "Crew"),
    "AM Office — 6:45 AM–12:00 PM": (time(6, 45), time(12, 0), "Office"),
    "Office Back Up — 6:45 AM–10:30 AM": (time(6, 45), time(10, 30), "Office"),
    "PM Office — 2:00 PM–7:00 PM": (time(14, 0), time(19, 0), "Office"),
    "7:00 AM–11:00 AM": (time(7, 0), time(11, 0), "Crew"),
    "3:00 PM–7:00 PM": (time(15, 0), time(19, 0), "Crew"),
    "Office 7:00 AM–11:00 AM": (time(7, 0), time(11, 0), "Office"),
    "Office 3:00 PM–7:00 PM": (time(15, 0), time(19, 0), "Office"),
}

SPECIAL_SHIFT_LABELS = {
    "7:00 AM–11:00 AM", "3:00 PM–7:00 PM",
    "Office 7:00 AM–11:00 AM", "Office 3:00 PM–7:00 PM",
}

NORMAL_SHIFT_CAPACITY = {
    "Crew AM — 6:45 AM–12:00 PM": 2,
    "Back Up AM — 8:00 AM–11:30 AM": 1,
    "Crew PM — 2:00 PM–7:00 PM": 2,
    "Back Up PM — 2:00 PM–5:00 PM": 1,
    "AM Office — 6:45 AM–12:00 PM": 1,
    "Office Back Up — 6:45 AM–10:30 AM": 1,
    "PM Office — 2:00 PM–7:00 PM": 1,
}

SPECIAL_STAFFING_LIMITS = {"Crew": (2, 3), "Office": (1, 1)}


def _first_name(value):
    text = str(value or "").strip()
    return text.split()[0] if text else "Employee"


def _eligible_users(users, department):
    allowed_roles = {department, "Cross-Trained", "Boss", "Developer"}
    return users[users["role"].isin(allowed_roles)]


def _shift_count(existing, shift_date, shift_label):
    start_time, end_time, department = SHIFT_PRESETS[shift_label]
    if existing.empty:
        return 0
    return int((
        (existing["starts_at"].dt.date == shift_date)
        & (existing["starts_at"].dt.time == start_time)
        & (existing["ends_at"].dt.time == end_time)
        & (existing["department"] == department)
    ).sum())


def _shift_options_for_role(role, period=None, special_hours=False):
    if role == "Crew":
        options = [label for label, values in SHIFT_PRESETS.items() if values[2] == "Crew"]
    elif role == "Office":
        options = [label for label, values in SHIFT_PRESETS.items() if values[2] == "Office"]
    else:
        options = list(SHIFT_PRESETS)
    options = [
        label for label in options
        if (label in SPECIAL_SHIFT_LABELS) == special_hours
    ]
    if period:
        is_am = period == "AM"
        options = [
            label for label in options
            if (SHIFT_PRESETS[label][0].hour < 12) == is_am
        ]
    return options


def _is_backup_shift(row):
    start = pd.Timestamp(row["starts_at"]).time().replace(second=0, microsecond=0)
    end = pd.Timestamp(row["ends_at"]).time().replace(second=0, microsecond=0)
    return (start, end) in {
        (time(8, 0), time(11, 30)),
        (time(14, 0), time(17, 0)),
        (time(6, 45), time(10, 30)),
    }


def _role_can_cover_shift(role, row):
    if role in ("Cross-Trained", "Boss", "Developer"):
        return True
    if role == "Crew":
        return row["department"] == "Crew"
    if role == "Office":
        return row["department"] == "Office" or (
            row["department"] == "Crew" and _is_backup_shift(row)
        )
    return False


def _show_trade_staffing(upcoming, viewer_role):
    visible = upcoming[
        upcoming.apply(lambda row: _role_can_cover_shift(viewer_role, row), axis=1)
    ].copy()
    if visible.empty:
        st.info("No eligible shifts are currently posted.")
        return
    visible["work_date"] = visible["starts_at"].dt.date
    visible["period"] = visible["starts_at"].dt.hour.map(lambda hour: "AM" if hour < 12 else "PM")
    st.markdown("#### Available staffing")
    for (work_date, period), group in visible.groupby(["work_date", "period"], sort=True):
        day_type = "Weekend · " if work_date.weekday() >= 5 else ""
        st.markdown(
            f"**{work_date.strftime('%A, %m/%d/%Y')} — {day_type}{period}**"
        )
        crew = group[(group.department == "Crew") & ~group.apply(_is_backup_shift, axis=1)]
        crew_backup = group[(group.department == "Crew") & group.apply(_is_backup_shift, axis=1)]
        office = group[(group.department == "Office") & ~group.apply(_is_backup_shift, axis=1)]
        office_backup = group[(group.department == "Office") & group.apply(_is_backup_shift, axis=1)]
        if viewer_role in ("Crew", "Cross-Trained"):
            for name in crew.display_name.map(_first_name): st.write(f"Crew {period}: {name}")
            for name in crew_backup.display_name.map(_first_name): st.write(f"Crew {period} Back Up: {name}")
        if viewer_role in ("Office", "Cross-Trained"):
            if viewer_role == "Office":
                for name in crew_backup.display_name.map(_first_name): st.write(f"Crew {period} Back Up: {name}")
            for name in office.display_name.map(_first_name): st.write(f"Office {period}: {name}")
            for name in office_backup.display_name.map(_first_name): st.write(f"Office {period} Back Up: {name}")
        st.divider()


def _trade_shift_label(row):
    start = pd.Timestamp(row["starts_at"])
    period = "AM" if start.hour < 12 else "PM"
    if start.weekday() >= 5:
        slot = f"Weekend {row['department']} {period}"
    else:
        slot = f"{row['department']} {period}"
    if start.weekday() < 5 and _is_backup_shift(row):
        slot += " Back Up"
    return f"{start.strftime('%A, %m/%d/%Y')} — {slot}"


def _show_shift_switch(user, users):
    st.subheader("Switch Shifts", anchor=False)
    st.caption("A switch happens only after the other employee accepts it.")
    requests = load_shift_trade_requests(user["user_id"])
    inbox = requests[
        (requests["target_user_id"] == user["user_id"])
        & (requests["status"] == "Pending")
    ] if not requests.empty else requests

    if not inbox.empty:
        st.markdown(f"#### Requests for you ({len(inbox)})")
        for _, request in inbox.iterrows():
            with st.container(border=True):
                st.markdown(f"**{_first_name(request.requester_name)} wants to switch shifts with you.**")
                st.write(f"You would receive: {_trade_shift_label({'starts_at': request.offered_starts_at, 'ends_at': request.offered_ends_at, 'department': request.offered_department})}")
                st.write(f"They would receive: {_trade_shift_label({'starts_at': request.requested_starts_at, 'ends_at': request.requested_ends_at, 'department': request.requested_department})}")
                if pd.notna(request.request_note):
                    st.caption(str(request.request_note))
                accept, deny = st.columns(2)
                if accept.button("Accept switch", key=f"accept_trade_{request.trade_request_id}", use_container_width=True):
                    try:
                        review_shift_trade_request(request.trade_request_id, user["user_id"], "Accepted")
                        st.success("Shift switch accepted. The schedule has been updated."); st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if deny.button("Deny", key=f"deny_trade_{request.trade_request_id}", use_container_width=True):
                    review_shift_trade_request(request.trade_request_id, user["user_id"], "Denied")
                    st.info("Shift switch denied."); st.rerun()
    else:
        st.info("You do not have any new shift-switch requests.")

    st.markdown("#### Request a switch")
    upcoming = load_shifts(date.today(), date.today() + timedelta(days=60))
    own = upcoming[
        (upcoming["user_id"] == user["user_id"])
        & (upcoming["starts_at"] > datetime.now())
    ] if not upcoming.empty else upcoming
    if own.empty:
        st.info("You do not have an upcoming shift available to switch.")
    else:
        own_options = {int(row.shift_id): _trade_shift_label(row) for _, row in own.iterrows()}
        own_shift_id = st.selectbox("Your shift", list(own_options), format_func=own_options.get)
        own_shift = own[own["shift_id"] == own_shift_id].iloc[0]
        roles = users.set_index("user_id")["role"].to_dict()
        candidates = upcoming[
            (upcoming["user_id"] != user["user_id"])
            & (upcoming["starts_at"] > datetime.now())
        ].copy()
        candidates = candidates[candidates.apply(
            lambda row: (
                _role_can_cover_shift(roles.get(int(row.user_id), ""), own_shift)
                and _role_can_cover_shift(user["role"], row)
            ), axis=1,
        )]
        if candidates.empty:
            st.info("No qualified coworkers currently have an eligible shift to exchange.")
        else:
            candidate_options = {
                int(row.shift_id): f"{_first_name(row.display_name)} — {_trade_shift_label(row)}"
                for _, row in candidates.iterrows()
            }
            with st.form("request_shift_trade"):
                target_shift_id = st.selectbox(
                    "Coworker's shift", list(candidate_options),
                    format_func=candidate_options.get,
                )
                note = st.text_input("Message (optional)", placeholder="Why you need to switch")
                submitted = st.form_submit_button("Send switch request", use_container_width=True)
            if submitted:
                try:
                    create_shift_trade_request(
                        user["user_id"], own_shift_id, target_shift_id, note
                    )
                    st.success("Switch request sent to the other employee."); st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    if not requests.empty:
        st.markdown("#### Your request history")
        history = requests.copy()
        history["Employee"] = history.apply(
            lambda row: _first_name(row.target_name) if int(row.requester_user_id) == int(user["user_id"])
            else _first_name(row.requester_name), axis=1,
        )
        history["Status"] = history["status"]
        history["Requested"] = pd.to_datetime(history["created_at"]).dt.strftime(
            "%A, %m/%d/%Y"
        )
        st.dataframe(history[["Employee", "Requested", "Status"]], use_container_width=True, hide_index=True)


def _schedule_display_table(shifts):
    display = shifts.sort_values(
        ["starts_at", "ends_at", "display_name"]
    ).copy()

    def preset_name(row):
        start_value = row["starts_at"].time().replace(second=0, microsecond=0)
        end_value = row["ends_at"].time().replace(second=0, microsecond=0)
        for label, (start_time, end_time, department) in SHIFT_PRESETS.items():
            if (start_value, end_value, row["department"]) == (start_time, end_time, department):
                return label.split(" — ", 1)[0]
        return row["department"]

    display["Date"] = display["starts_at"].dt.strftime("%m/%d/%Y")
    display["Employee"] = display["display_name"].map(_first_name)
    display["Shift"] = display.apply(preset_name, axis=1)
    display["Hours"] = display.apply(
        lambda row: (
            row["starts_at"].strftime("%I:%M %p").lstrip("0")
            + "–"
            + row["ends_at"].strftime("%I:%M %p").lstrip("0")
        ),
        axis=1,
    )
    display["Role"] = display["department"]
    display["Notes"] = display["notes"].fillna("")
    return display[["Date", "Employee", "Shift", "Hours", "Role", "Notes"]]


def _style_schedule_table(display):
    def row_color(row):
        if row["Role"] == "Office":
            color = "background-color: #dcfce7; color: #14532d;"
        elif str(row["Shift"]).startswith("Back Up"):
            color = "background-color: #ede9fe; color: #4c1d95;"
        else:
            color = "background-color: #fef3c7; color: #713f12;"
        return [color] * len(row)

    return display.style.apply(row_color, axis=1)


def _staffing_names(day_shifts, department, period, backup=False):
    period_is_am = period == "AM"
    matching = day_shifts[
        (day_shifts["department"] == department)
        & ((day_shifts["starts_at"].dt.hour < 12) == period_is_am)
    ].copy()
    if matching.empty:
        return []
    work_date = matching.iloc[0]["starts_at"].date()
    is_weekend = work_date.weekday() >= 5
    if is_weekend:
        return [] if backup else matching["display_name"].map(_first_name).tolist()
    if department == "Crew":
        backup_times = {(time(8, 0), time(11, 30)), (time(14, 0), time(17, 0))}
    else:
        backup_times = {(time(6, 45), time(10, 30))}
    matching["is_backup"] = matching.apply(
        lambda row: (
            row["starts_at"].time().replace(second=0, microsecond=0),
            row["ends_at"].time().replace(second=0, microsecond=0),
        ) in backup_times,
        axis=1,
    )
    return matching[matching["is_backup"] == backup]["display_name"].map(_first_name).tolist()


def _staffing_line(label, regular_names, backup_names=None):
    names = ", ".join(regular_names) if regular_names else "Not assigned"
    if backup_names:
        names += " · B/U: " + ", ".join(backup_names)
    st.markdown(f"**{label}:** {names}")


def _crew_team_names(names, current_first_name):
    if not names:
        return '<span class="crew-unassigned">Not assigned</span>'
    return ", ".join(
        f'<mark class="crew-self-name">{escape(name)}</mark>'
        if name.casefold() == current_first_name.casefold()
        else escape(name)
        for name in names
    )


def _show_crew_today_team(day_shifts, current_display_name):
    current_first_name = _first_name(current_display_name)
    columns = st.columns(2)
    for column, period in zip(columns, ("AM", "PM")):
        crew = _crew_team_names(_staffing_names(day_shifts, "Crew", period), current_first_name)
        crew_backup_names = _staffing_names(day_shifts, "Crew", period, backup=True)
        crew_backup = _crew_team_names(crew_backup_names, current_first_name)
        office = _crew_team_names(_staffing_names(day_shifts, "Office", period), current_first_name)
        office_backup_names = _staffing_names(day_shifts, "Office", period, backup=True)
        office_backup = _crew_team_names(office_backup_names, current_first_name)
        crew_backup_text = f' <span class="crew-backup-separator">&middot;</span> <span class="crew-backup-label">B/U:</span> {crew_backup}' if crew_backup_names else ""
        office_backup_text = f' <span class="crew-backup-separator">&middot;</span> <span class="crew-backup-label">B/U:</span> {office_backup}' if office_backup_names else ""
        column.markdown(
            (
                f'<section class="crew-team-period crew-team-period--{period.lower()}">'
                f'<h3>{period}</h3>'
                f'<div class="crew-team-line"><span>Crew:</span><strong>{crew}{crew_backup_text}</strong></div>'
                f'<div class="crew-team-line"><span>Office:</span><strong>{office}{office_backup_text}</strong></div>'
                f'</section>'
            ),
            unsafe_allow_html=True,
        )


def _shift_category(row):
    start_value = row["starts_at"].time().replace(second=0, microsecond=0)
    end_value = row["ends_at"].time().replace(second=0, microsecond=0)
    period = "AM" if start_value.hour < 12 else "PM"
    department = str(row["department"])
    backup = (
        (department == "Crew" and (start_value, end_value) in {
            (time(8, 0), time(11, 30)), (time(14, 0), time(17, 0))
        })
        or (department == "Office" and (start_value, end_value) == (time(6, 45), time(10, 30)))
    )
    return f"{period} {department}" + (" Backup" if backup else "")


def _show_removal_staffing(day_shifts, period):
    categories = (
        "AM Crew", "AM Crew Backup", "AM Office", "AM Office Backup",
        "PM Crew", "PM Crew Backup", "PM Office",
    )
    categorized = day_shifts.copy()
    categorized["category"] = categorized.apply(_shift_category, axis=1)
    categorized = categorized[categorized["category"].str.startswith(period)].copy()
    st.markdown(f"### {period} Shift")
    for category in categories:
        if not category.startswith(period):
            continue
        names = categorized[categorized.category == category]["display_name"].map(_first_name).tolist()
        label = category.removeprefix(f"{period} ")
        st.markdown(f"**{label}:** {', '.join(names) if names else 'Not assigned'}")
    return categorized


def _show_daily_staffing_board(shifts, start_date, day_count=7):
    for day_offset in range(day_count):
        work_date = start_date + timedelta(days=day_offset)
        day_shifts = shifts[shifts["starts_at"].dt.date == work_date]
        if work_date == date.today() - timedelta(days=1):
            card_state = "yesterday"
        elif work_date < date.today():
            card_state = "past"
        elif work_date == date.today():
            card_state = "today"
        elif work_date == date.today() + timedelta(days=1):
            card_state = "tomorrow"
        else:
            card_state = "future"
        card_key = f"schedule_{card_state}_{work_date.isoformat().replace('-', '_')}"
        with st.container(border=True, key=card_key):
            if work_date == date.today():
                st.markdown(
                    f"""<div class="schedule-today-heading">
                        <span>TODAY</span>
                        {work_date.strftime('%m/%d/%Y')}
                    </div>""",
                    unsafe_allow_html=True,
                )
            elif work_date == date.today() - timedelta(days=1):
                st.markdown(
                    f"""<div class="schedule-yesterday-heading">
                        <span>YESTERDAY</span>
                        {work_date.strftime('%m/%d/%Y')}
                    </div>""",
                    unsafe_allow_html=True,
                )
            elif work_date == date.today() + timedelta(days=1):
                st.markdown(
                    f"""<div class="schedule-tomorrow-heading">
                        <span>TOMORROW</span>
                        {work_date.strftime('%m/%d/%Y')}
                    </div>""",
                    unsafe_allow_html=True,
                )
            else:
                st.subheader(work_date.strftime("%m/%d/%Y"), anchor=False)
            am_column, pm_column = st.columns(2)
            with am_column:
                st.markdown("### AM Shift")
                _staffing_line(
                    "Crew",
                    _staffing_names(day_shifts, "Crew", "AM"),
                    _staffing_names(day_shifts, "Crew", "AM", backup=True),
                )
                _staffing_line(
                    "Office",
                    _staffing_names(day_shifts, "Office", "AM"),
                    _staffing_names(day_shifts, "Office", "AM", backup=True),
                )
            with pm_column:
                st.markdown("### PM Shift")
                _staffing_line(
                    "Crew",
                    _staffing_names(day_shifts, "Crew", "PM"),
                    _staffing_names(day_shifts, "Crew", "PM", backup=True),
                )
                _staffing_line(
                    "Office",
                    _staffing_names(day_shifts, "Office", "PM"),
                )


def _show_individual_schedule_week(shifts, start_date):
    columns = st.columns(7)
    for day_offset, column in enumerate(columns):
        work_date = start_date + timedelta(days=day_offset)
        day_shifts = shifts[shifts["starts_at"].dt.date == work_date].sort_values("starts_at")
        with column:
            st.markdown(f"**{work_date:%a}**")
            st.caption(work_date.strftime("%m/%d"))
            if day_shifts.empty:
                st.markdown("*Off*")
                continue
            for _, shift in day_shifts.iterrows():
                start_time = shift["starts_at"].strftime("%I:%M %p").lstrip("0")
                end_time = shift["ends_at"].strftime("%I:%M %p").lstrip("0")
                backup = " · B/U" if _is_backup_shift(shift) else ""
                st.markdown(
                    f"**{shift['department']}{backup}**  \n{start_time}–{end_time}"
                )


def _monday_for(day):
    return day - timedelta(days=day.weekday())


def _week_range_label(start_date):
    end_date = start_date + timedelta(days=6)
    def ordinal(day_number):
        if 10 <= day_number % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day_number % 10, "th")
        return f"{day_number}{suffix}"

    return (
        f"{start_date.strftime('%m/%d/%Y')}–{end_date.strftime('%m/%d/%Y')}"
    )


def _weekly_hours_table(shifts, week_start):
    week_end = week_start + timedelta(days=6)
    week = shifts[
        (shifts["starts_at"].dt.date >= week_start)
        & (shifts["starts_at"].dt.date <= week_end)
    ].copy()
    if week.empty:
        return week
    week["Hours"] = (
        (week["ends_at"] - week["starts_at"]).dt.total_seconds() / 3600
    )
    summary = (
        week.groupby(["user_id", "display_name"], as_index=False)["Hours"]
        .sum()
        .sort_values(["display_name"])
        .rename(columns={"display_name": "Employee"})
    )
    summary["Hours"] = summary["Hours"].round(2)
    return summary[["Employee", "Hours"]]


def _show_weekly_hours(shifts, week_start, viewer):
    summary = _weekly_hours_table(shifts, week_start)
    can_view_everyone = viewer["role"] in ("Boss", "Developer")
    if can_view_everyone:
        st.subheader("Employee Hours", anchor=False)
    else:
        st.subheader("My Hours", anchor=False)
        summary = summary[summary["Employee"] == viewer["display_name"]]
    if summary.empty:
        message = (
            "No employee hours are scheduled for this week."
            if can_view_everyone
            else "You have no scheduled hours this week."
        )
        st.info(message)
    elif can_view_everyone:
        summary = summary.copy()
        summary["Employee"] = summary["Employee"].map(_first_name)
        st.dataframe(summary, use_container_width=True, hide_index=True)
    else:
        st.metric("Scheduled Hours", float(summary.iloc[0]["Hours"]))


def _special_label(department, period):
    hours = "7:00 AM–11:00 AM" if period == "AM" else "3:00 PM–7:00 PM"
    return f"Office {hours}" if department == "Office" else hours


def _build_automatic_assignments(normal_rows, users, start_date, end_date, existing):
    assignments = []
    counts = {}
    user_names = {int(row.user_id): row.display_name for _, row in users.iterrows()}
    work_date = start_date
    while work_date <= end_date:
        holiday, _ = is_schedule_holiday(work_date)
        special = work_date.weekday() >= 5 or holiday
        for _, normal in normal_rows[normal_rows.weekday_number == work_date.weekday()].iterrows():
            if int(normal.user_id) not in user_names:
                continue
            shift_label = normal.shift_label
            department = SHIFT_PRESETS[shift_label][2]
            if special:
                shift_label = _special_label(department, normal.period)
            start_time, end_time, department = SHIFT_PRESETS[shift_label]
            already = existing[
                (existing.user_id == int(normal.user_id))
                & (existing.starts_at.dt.date == work_date)
                & ((existing.starts_at.dt.hour < 12) == (normal.period == "AM"))
            ]
            if not already.empty:
                continue
            capacity = (SPECIAL_STAFFING_LIMITS[department][1] if special
                        else NORMAL_SHIFT_CAPACITY[shift_label])
            key = (work_date, shift_label)
            used = counts.get(key, _shift_count(existing, work_date, shift_label))
            if used >= capacity:
                continue
            counts[key] = used + 1
            assignments.append({
                "user_id": int(normal.user_id),
                "display_name": user_names[int(normal.user_id)],
                "starts_at": datetime.combine(work_date, start_time),
                "ends_at": datetime.combine(work_date, end_time),
                "department": department,
                "notes": "Auto-generated from normal schedule",
            })
        work_date += timedelta(days=1)
    return assignments


def _has_approved_time_off(approved, user_id, work_date, period):
    if approved.empty:
        return False
    matches = approved[
        (approved["user_id"] == int(user_id))
        & (approved["start_date"] <= work_date)
        & (approved["end_date"] >= work_date)
        & (approved["period"].isin([period, "Both"]))
    ]
    return not matches.empty


def _show_schedule_time_off_notice(approved, start_date, end_date):
    relevant = approved[
        (approved["start_date"] <= end_date)
        & (approved["end_date"] >= start_date)
    ] if not approved.empty else approved
    if relevant.empty:
        return
    st.warning(f"Approved Time Off: {len(relevant)} request(s) affect this schedule.")
    with st.expander("View approved time off", expanded=True):
        for _, request in relevant.iterrows():
            st.markdown(
                f"**{_first_name(request.display_name)}** — "
                f"{_time_off_date_label(request)} — **{request.period}**"
            )


def _task_counts(tasks):
    open_tasks = tasks[~tasks["status"].isin(["Completed", "Skipped", "Refused"])] if not tasks.empty else tasks
    overdue = open_tasks[open_tasks["due_at"] < datetime.now()] if not open_tasks.empty else open_tasks
    meds = open_tasks[open_tasks["task_type"] == "Medication"] if not open_tasks.empty else open_tasks
    return len(open_tasks), len(overdue), len(meds)


def _show_task_cards(tasks, editable=True):
    if tasks.empty:
        st.info("No tasks for this view."); return
    for _, task in tasks.iterrows():
        dog = f" · {task['dog_name']}" if task.get("dog_name") else ""
        assignee = f" · Assigned to {task['assigned_to']}" if task.get("assigned_to") else ""
        due_at = task["due_at"]
        if due_at.hour == 23 and due_at.minute == 59:
            due_period = "Both"
        elif due_at.hour <= 12:
            due_period = "AM Shift"
        else:
            due_period = "PM Shift"
        due = f"{due_at:%m/%d/%Y} · {due_period}"
        icon = "💊" if task["task_type"] == "Medication" else "✓"
        with st.expander(f"{icon} {task['title']}{dog} — {task['status']}"):
            st.caption(f"{task['department']} · {task['priority']} · Due {due}{assignee}")
            if task.get("details"):
                st.write(task["details"])
            if task.get("completion_note"):
                st.info(f"Result: {task['completion_note']}")
            if editable and task["status"] not in ("Completed", "Skipped", "Refused"):
                with st.form(f"task_status_{int(task['task_id'])}"):
                    choices = ["In Progress", "Completed", "Needs Attention"]
                    if task["task_type"] == "Medication":
                        choices += ["Refused", "Skipped"]
                    status = st.selectbox("Update status", choices)
                    note = st.text_input("Note", placeholder="Required for refused, skipped, or needs attention")
                    save = st.form_submit_button("Save update", use_container_width=True)
                if save:
                    if status in ("Refused", "Skipped", "Needs Attention") and not note.strip():
                        st.error("Add a note explaining this result.")
                    else:
                        update_task_status(task["task_id"], status, note, current_user()["user_id"])
                        st.success("Task updated."); st.rerun()


def _show_crew_dog_roster():
    present = load_dogs()
    boarding_values = pd.to_numeric(
        present.get("boarding_status", pd.Series(0, index=present.index)),
        errors="coerce",
    ).fillna(0).astype(int)
    daycare = present[boarding_values == 0].copy()
    boarding = present[boarding_values == 1].copy()

    st.title("Today’s Dogs")
    st.caption("Live list of dogs currently checked in")
    search = st.text_input(
        "Search dogs", placeholder="Search by dog name, breed, or room",
        key="crew_roster_search",
    ).strip().casefold()

    def roster_table(group):
        if search and not group.empty:
            searchable = group.astype(str).apply(
                lambda column: column.str.casefold().str.contains(
                    search, regex=False, na=False,
                )
            )
            group = group[searchable.any(axis=1)]
        columns = [column for column in (
            "dog_name", "dog_breed", "assigned_room_number",
        ) if column in group.columns]
        display = group[columns].rename(columns={
            "dog_name": "Dog", "dog_breed": "Breed",
            "assigned_room_number": "Room",
        })
        sort_columns = [column for column in ("Room", "Dog") if column in display.columns]
        return display.sort_values(sort_columns, na_position="last") if sort_columns else display

    tabs = st.tabs([f"Daycare ({len(daycare)})", f"Boarding ({len(boarding)})"])
    for tab, label, group in (
        (tabs[0], "daycare", daycare), (tabs[1], "boarding", boarding),
    ):
        with tab:
            display = roster_table(group)
            if display.empty:
                st.info(f"No {label} dogs match this view.")
            else:
                st.dataframe(display, use_container_width=True, hide_index=True)


def show_overview():
    user = current_user(); today = date.today(); tomorrow = today + timedelta(days=1)
    if user["role"] == "Crew":
        _show_crew_dog_roster()
        return
    shifts = load_shifts(today, tomorrow)
    my_shifts = shifts[shifts["user_id"] == user["user_id"]] if not shifts.empty else shifts
    shift_value, shift_detail = shift_summary(my_shifts, today)
    phase_title, phase_detail = (
        crew_right_now(my_shifts, today)
        if user["role"] == "Crew" else day_phase()
    )
    if user["role"] == "Crew":
        show_crew_briefing_header(
            user, shift_value, shift_detail, phase_title, phase_detail,
        )
        team_date, team_heading, team_day_word = crew_team_day(today)
        team_shifts = shifts[
            shifts["starts_at"].dt.date == team_date
        ] if not shifts.empty else shifts
        st.markdown(f"## {team_heading}")
        if team_shifts.empty:
            st.info(f"No team schedule has been posted for {team_day_word}.")
        else:
            _show_crew_today_team(team_shifts, user["display_name"])

        present = load_dogs()
        boarding_values = pd.to_numeric(
            present.get("boarding_status", pd.Series(0, index=present.index)),
            errors="coerce",
        ).fillna(0).astype(int)
        dog_groups = (
            ("Daycare", present[boarding_values == 0], "crew_daycare_search"),
            ("Boarding", present[boarding_values == 1], "crew_boarding_search"),
        )
        for group_name, group, search_key in dog_groups:
            with st.expander(f"Dogs — {group_name} ({len(group)})", expanded=False):
                if group.empty:
                    st.info(f"No {group_name.lower()} dogs are currently checked in.")
                    continue
                dog_search = st.text_input(
                    f"Find a {group_name.lower()} dog",
                    placeholder="Search by dog name, breed, or room",
                    key=search_key,
                ).strip().casefold()
                group_view = group.copy()
                if dog_search:
                    searchable = group_view.astype(str).apply(
                        lambda column: column.str.casefold().str.contains(
                            dog_search, regex=False, na=False,
                        )
                    )
                    group_view = group_view[searchable.any(axis=1)]
                display_columns = [column for column in (
                    "dog_name", "dog_breed", "assigned_room_number",
                ) if column in group_view.columns]
                display = group_view[display_columns].rename(columns={
                    "dog_name": "Dog", "dog_breed": "Breed",
                    "assigned_room_number": "Room",
                })
                sort_columns = [column for column in ("Room", "Dog") if column in display.columns]
                if sort_columns:
                    display = display.sort_values(sort_columns, na_position="last")
                if display.empty:
                    st.info("No dogs match this search.")
                else:
                    st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("## Start here")
        action_columns = st.columns(2)
        navigate_button(
            action_columns[0], "Boarding care", "Boarding Care",
            "crew_briefing_boarding", primary=True,
        )
        navigate_button(
            action_columns[1], "View my schedule", "Schedule",
            "crew_briefing_schedule",
        )
        st.markdown("## Tomorrow")
        tomorrow_rows = my_shifts[
            my_shifts["starts_at"].dt.date == tomorrow
        ] if not my_shifts.empty else my_shifts
        if tomorrow_rows.empty:
            st.write("No shift posted for tomorrow.")
        else:
            st.dataframe(
                _schedule_display_table(tomorrow_rows)[["Shift", "Hours", "Role"]],
                use_container_width=True,
                hide_index=True,
            )
        return

    if user["role"] == "Office":
        present = load_dogs()
        arrivals, departures = load_day_summary(today)
        show_office_front_desk_header(
            user, shift_value, shift_detail, len(present),
            len(arrivals), len(departures),
        )
        action_columns = st.columns(3)
        navigate_button(action_columns[0], "Open attendance", "Attendance", "office_front_attendance", primary=True)
        navigate_button(action_columns[1], "Manage assignments", "Assignments", "office_front_assignments")
        navigate_button(action_columns[2], "Dog management", "Dog Management", "office_front_dogs")

        st.markdown("## Today’s front desk")
        search = st.text_input(
            "Search today’s dogs",
            placeholder="Search by dog name, breed, or room",
            key="office_front_search",
        ).strip().casefold()

        def filtered(frame):
            if not search or frame.empty:
                return frame
            searchable = frame.astype(str).apply(
                lambda column: column.str.casefold().str.contains(search, regex=False, na=False)
            )
            return frame[searchable.any(axis=1)]

        tabs = st.tabs([
            f"Present {len(present)}", f"Arrivals {len(arrivals)}",
            f"Departures {len(departures)}",
        ])
        with tabs[0]:
            present_view = filtered(present)
            columns = [column for column in (
                "dog_name", "dog_breed", "assigned_room_number", "boarding_status",
            ) if column in present_view.columns]
            if present_view.empty:
                st.info("No present dogs match this search.")
            else:
                display = present_view[columns].rename(columns={
                    "dog_name": "Dog", "dog_breed": "Breed",
                    "assigned_room_number": "Room", "boarding_status": "Boarding",
                })
                st.dataframe(display, use_container_width=True, hide_index=True)
        with tabs[1]:
            arrival_view = filtered(arrivals)
            if arrival_view.empty:
                st.info("No arrivals match this search.")
            else:
                st.dataframe(arrival_view, use_container_width=True, hide_index=True)
        with tabs[2]:
            departure_view = filtered(departures)
            if departure_view.empty:
                st.info("No departures match this search.")
            else:
                st.dataframe(departure_view, use_container_width=True, hide_index=True)

        st.markdown("## Team coverage")
        today_shifts = shifts[shifts["starts_at"].dt.date == today] if not shifts.empty else shifts
        _show_crew_today_team(today_shifts, user["display_name"])
        return

    show_companion_hero(
        user, shift_value, shift_detail, phase_title, phase_detail,
    )

    st.markdown("### Jump back in")
    quick_columns = st.columns(4)
    navigate_button(quick_columns[0], "Schedule", "Schedule", "companion_schedule", primary=True)
    navigate_button(quick_columns[1], "Attendance", "Attendance", "companion_attendance")
    navigate_button(quick_columns[2], "Dog operations", "Dashboard", "companion_dogs")
    navigate_button(quick_columns[3], "Report a problem", "Report a Problem", "companion_report")

    tabs = st.tabs(["Today", "Tomorrow", "Team schedule"])
    with tabs[0]:
        arrivals, departures = load_day_summary(today)
        a, d, s = st.columns(3)
        a.metric("Arriving today", len(arrivals))
        d.metric("Leaving today", len(departures))
        s.metric("Staff scheduled", len(shifts[shifts["starts_at"].dt.date == today]) if not shifts.empty else 0)
        if not arrivals.empty:
            st.subheader("Arrivals")
            st.dataframe(arrivals, use_container_width=True, hide_index=True)
        if not departures.empty:
            st.subheader("Departures")
            st.dataframe(departures, use_container_width=True, hide_index=True)
        if arrivals.empty and departures.empty:
            st.info("No boarding arrivals or departures are listed for today.")
    with tabs[1]:
        arrivals, departures = load_day_summary(tomorrow)
        a, d = st.columns(2)
        a.metric("Arriving", len(arrivals)); d.metric("Leaving", len(departures))
        if not arrivals.empty:
            st.subheader("Arrivals"); st.dataframe(arrivals, use_container_width=True, hide_index=True)
        if not departures.empty:
            st.subheader("Departures"); st.dataframe(departures, use_container_width=True, hide_index=True)
        if arrivals.empty and departures.empty:
            st.info("No boarding arrivals or departures are listed for tomorrow.")
    with tabs[2]:
        st.caption("Who is working today and tomorrow")
        _show_daily_staffing_board(shifts, today, day_count=2)
        if not shifts.empty:
            with st.expander("View exact shift hours"):
                st.dataframe(
                    _schedule_display_table(shifts),
                    use_container_width=True, hide_index=True
                )




def show_task_management():
    if current_user()["role"] not in ("Boss", "Developer"):
        st.error("Only the Boss can access Tasks & Reminders Management."); return
    st.title("Task & Reminder Management")
    tabs = st.tabs(["Create", "All tasks"])
    users = load_users(); users = users[users["role"] != "Developer"].copy()
    dogs = load_all_dogs()
    user_options = {0: "Everyone"}
    user_options.update({int(row.user_id): _first_name(row.display_name) for _, row in users.iterrows()})
    dog_options = {0: "No dog"}
    dog_options.update({int(row.dog_id): row.dog_name for _, row in dogs.iterrows()})
    with tabs[0]:
        with st.form("create_operations_task"):
            title = st.text_input("Task or reminder")
            details = st.text_area("Instructions")
            c1, c2, c3 = st.columns(3)
            department = c1.selectbox("Section", ["Crew", "Office", "All"])
            task_type = c2.selectbox("Type", ["General", "Medication", "Grooming", "Feeding", "Cleaning", "Arrival", "Departure", "Care"])
            priority = c3.selectbox("Priority", ["Normal", "High", "Urgent", "Low"])
            c4, c5 = st.columns(2)
            due_date = c4.date_input("Due date", value=date.today(), format="MM/DD/YYYY")
            due_shift = c5.selectbox("Due shift", ["AM Shift", "PM Shift", "Both"])
            dog_id = st.selectbox("Dog", list(dog_options), format_func=dog_options.get)
            assignee = st.selectbox("Assign to", list(user_options), format_func=user_options.get)
            submitted = st.form_submit_button("Create task", use_container_width=True)
        if submitted:
            if not title.strip(): st.error("Enter a task name.")
            else:
                due_times = {
                    "AM Shift": time(12, 0),
                    "PM Shift": time(19, 0),
                    "Both": time(23, 59),
                }
                create_task({"title": title, "details": details, "department": department,
                             "task_type": task_type, "priority": priority,
                             "due_at": datetime.combine(due_date, due_times[due_shift]),
                             "dog_id": dog_id or None, "assigned_user_id": assignee or None},
                            current_user()["user_id"])
                st.success("Task created."); st.rerun()
    with tabs[1]:
        start = st.date_input("From", value=date.today() - timedelta(days=1), format="MM/DD/YYYY", key="manage_task_start")
        end = st.date_input("Through", value=date.today() + timedelta(days=7), format="MM/DD/YYYY", key="manage_task_end")
        _show_task_cards(load_tasks(start, end))


def show_schedule():
    st.title("Work Schedule")
    user = current_user(); users = load_users()
    users = users[users["role"] != "Developer"].copy()
    can_manage = user["role"] in ("Developer", "Boss")
    can_remove = can_manage
    can_trade = user["role"] in ("Crew", "Office", "Cross-Trained")
    schedule_tabs = ["Schedule"]
    if can_manage:
        schedule_tabs.append("Add shift")
    if can_remove:
        schedule_tabs.append("Remove/Change Shifts")
    if can_trade:
        schedule_tabs.append("Switch Shifts")
    tabs = st.tabs(schedule_tabs)
    with tabs[0]:
        selected_date = st.date_input(
            "Schedule containing", value=date.today(), key="schedule_start",
            format="MM/DD/YYYY",
            help="The schedule always begins on Monday and displays two full weeks."
        )
        start = _monday_for(selected_date)
        next_week = start + timedelta(days=7)
        end = start + timedelta(days=13)
        shifts = load_shifts(start, end)
        approved_time_off = load_time_off_requests(status="Approved")
        schedule_view = "Team schedule"
        selected_employee_id = None
        if can_manage:
            schedule_view = st.segmented_control(
                "Schedule view",
                ["Team schedule", "Individual employee"],
                default="Team schedule",
                key="management_schedule_view",
            ) or "Team schedule"
            if schedule_view == "Individual employee":
                employee_options = {
                    int(row.user_id): row.display_name for _, row in users.iterrows()
                }
                selected_employee_id = st.selectbox(
                    "Employee",
                    list(employee_options),
                    format_func=employee_options.get,
                    key="management_schedule_employee",
                )
        visible_shifts = shifts
        if selected_employee_id is not None:
            visible_shifts = shifts[
                shifts["user_id"] == int(selected_employee_id)
            ].copy()
        if can_manage:
            _show_schedule_time_off_notice(approved_time_off, start, end)
        if can_manage:
            if st.button("Generate biweekly schedule from employee profiles", use_container_width=True):
                normal_rows = load_normal_schedule()
                assignments = _build_automatic_assignments(normal_rows, users, start, end, shifts)
                assignments = [
                    item for item in assignments
                    if not _has_approved_time_off(
                        approved_time_off, item["user_id"], item["starts_at"].date(),
                        "AM" if item["starts_at"].hour < 12 else "PM"
                    )
                ]
                if assignments:
                    create_shifts_batch(assignments, user["user_id"])
                    st.success(f"Added {len(assignments)} normal shift assignment(s)."); st.rerun()
                else:
                    st.info("No new normal shifts were available to add.")
        st.caption(f"Biweekly schedule · {start.strftime('%m/%d/%Y')}–{end.strftime('%m/%d/%Y')}")
        st.header(_week_range_label(start))
        if schedule_view == "Individual employee":
            _show_individual_schedule_week(visible_shifts, start)
        else:
            _show_daily_staffing_board(visible_shifts, start, day_count=7)
        _show_weekly_hours(visible_shifts, start, user)
        st.header(_week_range_label(next_week))
        if schedule_view == "Individual employee":
            _show_individual_schedule_week(visible_shifts, next_week)
        else:
            _show_daily_staffing_board(visible_shifts, next_week, day_count=7)
        _show_weekly_hours(visible_shifts, next_week, user)
        if not visible_shifts.empty:
            with st.expander("View detailed shift table"):
                st.caption("Office: green · Crew: yellow · Backup Crew: purple")
                st.dataframe(
                    _style_schedule_table(_schedule_display_table(visible_shifts)),
                    use_container_width=True, hide_index=True
                )
    if can_manage:
        with tabs[1]:
            shift_date = st.date_input("Date", value=date.today(), format="MM/DD/YYYY", key="new_shift_date")
            is_weekend = shift_date.weekday() >= 5
            holiday_hours, holiday_name = is_schedule_holiday(shift_date)
            if user["role"] in ("Developer", "Boss") and not is_weekend:
                with st.expander("Holiday settings", expanded=holiday_hours):
                    st.caption("Management can make this date use holiday hours for everyone.")
                    holiday_enabled = st.checkbox(
                        "Use holiday hours", value=holiday_hours,
                        key=f"holiday_enabled_{shift_date}"
                    )
                    holiday_label = st.text_input(
                        "Holiday name", value=holiday_name,
                        placeholder="Example: Labor Day",
                        key=f"holiday_name_{shift_date}"
                    )
                    if st.button("Save holiday setting", key=f"save_holiday_{shift_date}"):
                        set_schedule_holiday(
                            shift_date, holiday_enabled, holiday_label, user["user_id"]
                        )
                        st.success("Holiday setting saved."); st.rerun()
            special_hours = is_weekend or holiday_hours
            if is_weekend:
                st.info("Weekend hours apply automatically: 7:00–11:00 AM and 3:00–7:00 PM.")
            elif holiday_hours:
                st.info(f"{holiday_name or 'Holiday'} hours: 7:00–11:00 AM and 3:00–7:00 PM.")
            day_shifts = load_shifts(shift_date, shift_date)
            available_labels = [
                label for label in SHIFT_PRESETS
                if (label in SPECIAL_SHIFT_LABELS) == special_hours
            ]
            am_shifts = [label for label in available_labels if SHIFT_PRESETS[label][0].hour < 12]
            pm_shifts = [label for label in available_labels if SHIFT_PRESETS[label][0].hour >= 12]

            st.markdown("#### AM Shift")
            add_am = st.checkbox("Add an AM shift", key="add_am_multi")
            am_shift_label = st.selectbox("AM shift", am_shifts, key="am_shift_multi")
            am_department = SHIFT_PRESETS[am_shift_label][2]
            am_eligible = _eligible_users(users, am_department)
            am_options = {
                int(row.user_id): _first_name(row.display_name)
                for _, row in am_eligible.iterrows()
            }
            am_existing = _shift_count(day_shifts, shift_date, am_shift_label)
            am_capacity = (
                SPECIAL_STAFFING_LIMITS[am_department][1]
                if special_hours else NORMAL_SHIFT_CAPACITY.get(am_shift_label)
            )
            if am_capacity is not None:
                if special_hours:
                    minimum = SPECIAL_STAFFING_LIMITS[am_department][0]
                    st.caption(
                        f"{am_existing} scheduled · target {minimum} · maximum {am_capacity}"
                    )
                else:
                    st.caption(f"{max(0, am_capacity - am_existing)} of {am_capacity} openings remaining")
            am_people = st.multiselect(
                "AM employees", list(am_options), format_func=am_options.get,
                key="am_people_multi", disabled=not add_am,
            )

            st.markdown("#### PM Shift")
            add_pm = st.checkbox("Add a PM shift", key="add_pm_multi")
            pm_shift_label = st.selectbox("PM shift", pm_shifts, key="pm_shift_multi")
            pm_department = SHIFT_PRESETS[pm_shift_label][2]
            pm_eligible = _eligible_users(users, pm_department)
            pm_options = {
                int(row.user_id): _first_name(row.display_name)
                for _, row in pm_eligible.iterrows()
            }
            pm_existing = _shift_count(day_shifts, shift_date, pm_shift_label)
            pm_capacity = (
                SPECIAL_STAFFING_LIMITS[pm_department][1]
                if special_hours else NORMAL_SHIFT_CAPACITY.get(pm_shift_label)
            )
            if pm_capacity is not None:
                if special_hours:
                    minimum = SPECIAL_STAFFING_LIMITS[pm_department][0]
                    st.caption(
                        f"{pm_existing} scheduled · target {minimum} · maximum {pm_capacity}"
                    )
                else:
                    st.caption(f"{max(0, pm_capacity - pm_existing)} of {pm_capacity} openings remaining")
            pm_people = st.multiselect(
                "PM employees", list(pm_options), format_func=pm_options.get,
                key="pm_people_multi", disabled=not add_pm,
            )

            with st.form("add_work_shift"):
                notes = st.text_input("Notes")
                submitted = st.form_submit_button("Add selected shifts", use_container_width=True)
            if submitted:
                if not add_am and not add_pm:
                    st.error("Check AM Shift, PM Shift, or both.")
                else:
                    errors = []
                    if add_am and not am_people:
                        errors.append("Select at least one AM employee.")
                    if add_pm and not pm_people:
                        errors.append("Select at least one PM employee.")
                    if am_capacity is not None and add_am and am_existing + len(am_people) > am_capacity:
                        errors.append(f"{am_shift_label} allows only {am_capacity} employee(s).")
                    if pm_capacity is not None and add_pm and pm_existing + len(pm_people) > pm_capacity:
                        errors.append(f"{pm_shift_label} allows only {pm_capacity} employee(s).")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        assignments = []
                        for shift_label, employee_ids, enabled in (
                            (am_shift_label, am_people, add_am),
                            (pm_shift_label, pm_people, add_pm),
                        ):
                            if not enabled:
                                continue
                            start_time, end_time, department = SHIFT_PRESETS[shift_label]
                            labels = am_options if shift_label == am_shift_label else pm_options
                            for employee_id in employee_ids:
                                assignments.append({
                                    "user_id": employee_id,
                                    "display_name": labels[employee_id],
                                    "starts_at": datetime.combine(shift_date, start_time),
                                    "ends_at": datetime.combine(shift_date, end_time),
                                    "department": department,
                                    "notes": notes,
                                })
                        try:
                            create_shifts_batch(assignments, user["user_id"])
                            st.success(f"{len(assignments)} shift assignment(s) added."); st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
    if can_remove:
        with tabs[2]:
            st.subheader("Remove or Change a Shift", anchor=False)
            st.caption("Select the date and AM/PM period, then remove the employee who needs to be replaced or changed.")
            change_date = st.date_input(
                "Schedule date", value=date.today(), format="MM/DD/YYYY",
                key="schedule_change_date"
            )
            change_period = st.radio(
                "Which shift?", ["AM", "PM"], horizontal=True,
                key="schedule_change_period"
            )
            day_schedule = load_shifts(change_date, change_date)
            if day_schedule.empty:
                st.info("Nobody is scheduled on this date.")
            else:
                categorized = _show_removal_staffing(day_schedule, change_period)
                if categorized.empty:
                    st.info(f"Nobody is scheduled for the {change_period} shift.")
                    return
                change_options = {
                    int(row.shift_id): (
                        f"{row.category} — {_first_name(row.display_name)} — "
                        f"{row.starts_at.strftime('%I:%M %p').lstrip('0')}"
                    ) for _, row in categorized.iterrows()
                }
                with st.form("remove_or_switch_shift"):
                    shift_id = st.selectbox("Scheduled shift", list(change_options), format_func=change_options.get)
                    reason = st.selectbox(
                        "Reason", ["Called out", "Approved time off", "Shift switch", "Scheduling correction"]
                    )
                    detail = st.text_input("Additional note")
                    submitted_change = st.form_submit_button("Remove selected shift", use_container_width=True)
                if submitted_change:
                    remove_shift(shift_id, f"{reason}. {detail}".strip(), user["user_id"])
                    st.success("Shift removed. Use Add Shift to assign the replacement."); st.rerun()
    if can_trade:
        with tabs[1]:
            _show_shift_switch(user, users)


def _time_off_date_label(row):
    start = row["start_date"]
    end = row["end_date"]
    if hasattr(start, "date"):
        start = start.date()
    if hasattr(end, "date"):
        end = end.date()
    if start == end:
        return start.strftime("%m/%d/%Y")
    return (
        f"{start.strftime('%m/%d/%Y')}–{end.strftime('%m/%d/%Y')}"
    )


def show_time_off():
    user = current_user()
    st.title("Time Off")
    if user["role"] in ("Boss", "Developer"):
        requests = load_time_off_requests()
        pending = requests[requests.status == "Pending"] if not requests.empty else requests
        st.subheader(f"Approval Inbox ({len(pending)})")
        if pending.empty:
            st.info("There are no pending time-off requests.")
        else:
            for _, request in pending.iterrows():
                with st.container(border=True):
                    st.markdown(f"### {_first_name(request.display_name)}")
                    st.write(f"**When:** {_time_off_date_label(request)}")
                    st.write(f"**Shift:** {request.period}")
                    if request.request_note:
                        st.write(f"**Employee note:** {request.request_note}")
                    with st.form(f"review_time_off_{int(request.request_id)}"):
                        decision = st.radio(
                            "Decision", ["Approve", "Deny"], horizontal=True,
                            key=f"decision_{int(request.request_id)}"
                        )
                        note = st.text_input("Response note")
                        submitted = st.form_submit_button("Submit decision", use_container_width=True)
                    if submitted:
                        removed = review_time_off_request(
                            request.request_id, decision == "Approve", note, user["user_id"]
                        )
                        st.success(
                            f"Request {decision.lower()}d. {removed} scheduled shift(s) removed."
                        ); st.rerun()
        with st.expander("Reviewed requests"):
            reviewed = requests[requests.status != "Pending"] if not requests.empty else requests
            if reviewed.empty:
                st.info("No requests have been reviewed yet.")
            else:
                reviewed_display = reviewed.copy()
                reviewed_display["display_name"] = reviewed_display["display_name"].map(_first_name)
                reviewed_display["reviewed_by"] = reviewed_display["reviewed_by"].map(_first_name)
                reviewed_display["Dates"] = reviewed_display.apply(_time_off_date_label, axis=1)
                st.dataframe(
                    reviewed_display[["display_name", "Dates", "period", "status", "reviewed_by", "review_note"]].rename(
                        columns={"display_name": "Employee", "period": "Shift", "status": "Status",
                                 "reviewed_by": "Reviewed By", "review_note": "Response"}
                    ), use_container_width=True, hide_index=True
                )
        return

    tabs = st.tabs(["Request time off", "My requests"])
    with tabs[0]:
        with st.form("request_time_off"):
            start_date = st.date_input("First day", value=date.today() + timedelta(days=1), format="MM/DD/YYYY")
            end_date = st.date_input("Last day", value=date.today() + timedelta(days=1), format="MM/DD/YYYY")
            period = st.radio("Shift requested off", ["AM", "PM", "Both"], horizontal=True)
            note = st.text_area("Reason or note (optional)")
            submitted = st.form_submit_button("Send request to Boss", use_container_width=True)
        if submitted:
            try:
                create_time_off_request(user["user_id"], start_date, end_date, period, note)
                st.success("Your request was sent to Boss for approval."); st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with tabs[1]:
        requests = load_time_off_requests(user_id=user["user_id"])
        if requests.empty:
            st.info("You have not submitted any time-off requests.")
        else:
            for _, request in requests.iterrows():
                status_message = f"{request.status}: {_time_off_date_label(request)} · {request.period}"
                if request.status == "Approved":
                    st.success(status_message)
                elif request.status == "Denied":
                    st.error(status_message)
                else:
                    st.warning(status_message)
                if request.review_note:
                    st.caption(f"Boss response: {request.review_note}")


def show_accounts():
    user = current_user()
    if user["role"] not in ("Developer", "Boss"):
        st.error("Account management access is required."); return
    st.title("Worker Accounts")
    tab_names = ["Accounts", "Create account", "Normal schedules"]
    if user["role"] == "Developer":
        tab_names.append("Delete account")
    tabs = st.tabs(tab_names)
    with tabs[0]:
        users = load_users(active_only=False)
        if user["role"] == "Boss":
            users = users[users["role"] != "Developer"].copy()
        st.dataframe(users, use_container_width=True, hide_index=True)
        options = {int(row.user_id): f"{row.display_name} — {row.role}" for _, row in users.iterrows()}
        selected = st.selectbox("Employee", list(options), format_func=options.get, key="account_to_edit")
        row = users[users.user_id == selected].iloc[0]
        if user["role"] == "Developer":
            with st.form("edit_full_account"):
                first_name = st.text_input("First name", value=str(row.first_name))
                last_name = st.text_input("Last name", value=str(row.last_name))
                username = st.text_input("Username", value=str(row.username))
                role = st.selectbox("Role", list(ROLES), index=list(ROLES).index(row.role))
                active = st.checkbox("Account active", value=bool(row.active))
                new_credential = st.text_input(
                    "Set a new PIN or password (leave blank to keep current)", type="password",
                    help="Existing credentials cannot be displayed because they are one-way hashed."
                )
                save = st.form_submit_button("Save account", use_container_width=True)
            if save:
                try:
                    updated = update_user_account(
                        selected, first_name, last_name, username, role, active,
                        new_credential, user["user_id"]
                    )
                    if int(selected) == int(user["user_id"]):
                        st.session_state.current_user.update(updated)
                    st.success("Account updated."); st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            with st.form("edit_worker_access"):
                allowed_roles = [r for r in ROLES if r != "Developer"]
                role = st.selectbox("Role", allowed_roles, index=allowed_roles.index(row.role) if row.role in allowed_roles else 0)
                active = st.checkbox("Account active", value=bool(row.active))
                save = st.form_submit_button("Save access", use_container_width=True)
            if save:
                set_user_access(selected, role, active, user["user_id"])
                st.success("Account access updated."); st.rerun()
    with tabs[1]:
        with st.form("create_worker_account"):
            first_name = st.text_input("First name")
            last_name = st.text_input("Last name")
            username = st.text_input("Username")
            temp_password = st.text_input(
                "Worker PIN or management password",
                type="password",
                help=(
                    "Crew, Office, and Cross-Trained staff use a 3-digit PIN. Boss uses a password of at least 10 characters."
                    if user["role"] == "Boss"
                    else "Crew, Office, and Cross-Trained staff use a 3-digit PIN. Management accounts use a password of at least 10 characters."
                )
            )
            choices = list(ROLES) if user["role"] == "Developer" else [r for r in ROLES if r != "Developer"]
            role = st.selectbox("Role", choices)
            submitted = st.form_submit_button("Create account", use_container_width=True)
        if submitted:
            try:
                create_user(username, first_name, last_name, temp_password, role, user["user_id"], must_change=False)
                credential = "password" if uses_password(role) else "PIN"
                st.success(f"Account created. The employee can sign in with that {credential} immediately.")
            except Exception as exc: st.error(str(exc))
    with tabs[2]:
        st.caption("Set the days and shifts this employee normally works. This becomes the automatic schedule template.")
        users = users[users["role"] != "Developer"].copy()
        schedule_options = {
            int(row.user_id): f"{row.display_name} — {row.role}" for _, row in users.iterrows()
        }
        schedule_user = st.selectbox(
            "Employee", list(schedule_options), format_func=schedule_options.get,
            key="normal_schedule_employee"
        )
        employee_row = users[users.user_id == schedule_user].iloc[0]
        saved = load_normal_schedule(schedule_user)
        saved_map = {(int(row.weekday_number), row.period): row.shift_label for _, row in saved.iterrows()}
        role = str(employee_row.role)
        with st.form("normal_schedule_form"):
            selections = []
            for weekday_number, weekday_name in enumerate(
                ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
            ):
                st.markdown(f"**{weekday_name}**")
                columns = st.columns(2)
                for column, period in zip(columns, ("AM", "PM")):
                    is_weekend_day = weekday_number >= 5
                    choices = ["Off"] + _shift_options_for_role(
                        role, period, special_hours=is_weekend_day
                    )
                    current = saved_map.get((weekday_number, period), "Off")
                    choice = column.selectbox(
                        period, choices, index=choices.index(current) if current in choices else 0,
                        key=f"normal_{schedule_user}_{weekday_number}_{period}"
                    )
                    if choice != "Off":
                        selections.append((weekday_number, period, choice))
            save_normal = st.form_submit_button("Save normal schedule", use_container_width=True)
        if save_normal:
            save_normal_schedule(schedule_user, selections, user["user_id"])
            sync_start = _monday_for(date.today())
            sync_end = sync_start + timedelta(days=13)
            clear_generated_shifts(
                schedule_user, sync_start, sync_end, user["user_id"]
            )
            normal_rows = load_normal_schedule(schedule_user)
            existing = load_shifts(sync_start, sync_end)
            assignments = _build_automatic_assignments(
                normal_rows, users, sync_start, sync_end, existing
            )
            approved = load_time_off_requests(user_id=schedule_user, status="Approved")
            assignments = [
                item for item in assignments
                if not _has_approved_time_off(
                    approved, item["user_id"], item["starts_at"].date(),
                    "AM" if item["starts_at"].hour < 12 else "PM"
                )
            ]
            if assignments:
                create_shifts_batch(assignments, user["user_id"])
            st.success(
                f"Normal schedule saved and {len(assignments)} dated shift(s) added to the current biweekly schedule."
            ); st.rerun()
    if user["role"] == "Developer":
        with tabs[3]:
            deletable = users[users.user_id != user["user_id"]]
            if deletable.empty:
                st.info("There are no other accounts to delete.")
            else:
                delete_options = {
                    int(row.user_id): f"{row.display_name} — {row.username} — {row.role}"
                    for _, row in deletable.iterrows()
                }
                with st.form("permanent_account_delete"):
                    selected_delete = st.selectbox(
                        "Account", list(delete_options), format_func=delete_options.get
                    )
                    selected_row = deletable[deletable.user_id == selected_delete].iloc[0]
                    confirmation = st.text_input(
                        f"Type {selected_row.username} to confirm permanent deletion"
                    )
                    delete_submitted = st.form_submit_button(
                        "Permanently delete account", use_container_width=True
                    )
                if delete_submitted:
                    if confirmation.strip().lower() != selected_row.username.lower():
                        st.error("The username confirmation does not match.")
                    else:
                        delete_user(selected_delete, user["user_id"])
                        st.success("Account permanently deleted."); st.rerun()


def show_audit():
    if current_user()["role"] != "Developer":
        st.error("Developer access is required."); return
    st.title("Developer & Audit")
    st.caption("Deployment remains disabled. This view verifies local operational activity.")
    st.dataframe(load_audit(), use_container_width=True, hide_index=True)
