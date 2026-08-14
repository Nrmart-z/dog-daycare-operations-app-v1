from datetime import date, datetime
from html import escape

import pandas as pd
import streamlit as st
from auth import current_user

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

from boarding_care_service import (
    MEALS, add_boarding_note, confirm_medication, load_boarding_care,
    load_stay_history, pick_up_bowl, place_food, save_care_profile,
)
from operations_service import is_schedule_holiday, load_shifts
from room_capacity import room_section


MEAL_ROOM_ORDER = (
    "Petite Suites", "Condo Suites", "Kennels", "Crate Room",
    "Back Hall", "Front Kennel", "Floors", "Other",
)
MEAL_ROOM_LABELS = {
    "Petite Suites": "Petite Room",
    "Condo Suites": "Condo",
    "Kennels": "Kennel",
    "Crate Room": "Crate Room",
    "Back Hall": "Back Hall",
    "Front Kennel": "Front Kennel",
    "Floors": "Floors",
    "Other": "Other Rooms",
}


def _queue_stamp_confirmation(employee, dog_name, action):
    st.session_state["boarding_stamp_confirmation"] = (
        f"Saved & stamped — {employee} · {dog_name} · {action} · "
        f"{datetime.now():%I:%M %p}".replace(" 0", " ")
    )


def _show_stamp_confirmation():
    message = st.session_state.pop("boarding_stamp_confirmation", None)
    if message:
        st.success(message, icon="✅")


def _can_edit_boarding(user, shifts, now=None):
    if not user:
        return False
    if user.get("role") in ("Developer", "Boss"):
        return True
    if shifts is None or shifts.empty:
        return False
    now = pd.Timestamp(now or datetime.now())
    starts = pd.to_datetime(shifts["starts_at"], errors="coerce")
    ends = pd.to_datetime(shifts["ends_at"], errors="coerce")
    return bool(((starts <= now) & (ends >= now)).any())


def _has_boarding_sibling(boarders, row):
    sibling_group = row.get("sibling_group_id")
    if sibling_group is None or pd.isna(sibling_group):
        return False
    siblings = boarders[boarders["sibling_group_id"] == sibling_group]
    return siblings["dog_id"].nunique() > 1


def _room(row):
    name = str(row.get("room_name") or "").strip()
    number = str(row.get("room_number") or "").strip()
    return name or f"Room {number}"


def _stamp(value):
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%I:%M %p").lstrip("0")


def _history_date(value):
    if value is None or pd.isna(value):
        return "—"
    return pd.Timestamp(value).strftime("%m/%d/%Y")


def _history_time(value):
    if value is None or pd.isna(value):
        return "—"
    return pd.Timestamp(value).strftime("%I:%M %p").lstrip("0")


def _feeding_history_table(feedings):
    columns = ["Date", "Meal", "Food Placed", "Bowl Picked Up", "Appetite", "Notes"]
    if feedings.empty:
        return pd.DataFrame(columns=columns)
    display = pd.DataFrame({
        "Date": feedings["feeding_date"].map(_history_date),
        "Meal": feedings["meal"].fillna("—"),
        "Food Placed": feedings.apply(
            lambda row: (
                f"{row['placed_by']} · {_history_time(row['placed_at'])}"
                if pd.notna(row["placed_at"]) else "Not placed"
            ), axis=1,
        ),
        "Bowl Picked Up": feedings.apply(
            lambda row: (
                f"{row['picked_up_by']} · {_history_time(row['picked_up_at'])}"
                if pd.notna(row["picked_up_at"]) else "Waiting"
            ), axis=1,
        ),
        "Appetite": feedings["appetite"].fillna("—"),
        "Notes": feedings["meal_note"].fillna("—"),
    })
    return display[columns]


def _medication_history_table(meds):
    columns = ["Date", "Meal", "Result", "Completed By", "Time", "Notes"]
    if meds.empty:
        return pd.DataFrame(columns=columns)
    display = pd.DataFrame({
        "Date": meds["check_date"].map(_history_date),
        "Meal": meds["meal"].fillna("—"),
        "Result": meds["result"].fillna("—"),
        "Completed By": meds["employee_initials"].fillna("—"),
        "Time": meds["completed_at"].map(_history_time),
        "Notes": meds["administration_note"].fillna("—"),
    })
    return display[columns]


def _note_history_table(notes):
    columns = ["Date", "Time", "Added By", "Note"]
    if notes.empty:
        return pd.DataFrame(columns=columns)
    display = pd.DataFrame({
        "Date": notes["created_at"].map(_history_date),
        "Time": notes["created_at"].map(_history_time),
        "Added By": notes["employee_initials"].fillna("—"),
        "Note": notes["note_text"].fillna("—"),
    })
    return display[columns]


def _employee_picker():
    user = current_user()
    if user:
        initials = f"{user['first_name'][:1]}{user['last_name'][:1]}".upper()
        st.caption(f"Actions are recorded as {user['display_name']} ({initials}).")
        return initials
    st.markdown("### Employee on this phone")
    current = st.session_state.get("boarding_employee", "")
    with st.form("boarding_employee_form"):
        initials = st.text_input(
            "Initials", value=current, max_chars=10,
            placeholder="NM", help="This employee will be stamped on new confirmations."
        ).strip().upper()
        submitted = st.form_submit_button("Confirm employee", use_container_width=True)
    if submitted:
        if initials:
            st.session_state["boarding_employee"] = initials
            st.success(f"Working as {initials}")
            st.rerun()
        else:
            st.error("Enter employee initials.")
    current = st.session_state.get("boarding_employee", "")
    if current:
        st.info(f"Working as **{current}** — all new stamps use these initials.")
    return current


def _record_for(df, stay_id, meal):
    if df.empty:
        return None
    rows = df[(df["boarding_stay_id"] == stay_id) & (df["meal"] == meal)]
    return None if rows.empty else rows.iloc[0]


def _alerts(row):
    alerts = []
    status = str(row["allergy_status"])
    if status == "Allergy alert":
        alerts.append(f"ALLERGY: {row['allergy_details'] or 'See staff'}")
    elif status == "Not recorded":
        alerts.append("ALLERGIES NOT RECORDED")
    if bool(row["different_food_alert"]):
        alerts.append("DIFFERENT FOOD")
    setup = str(row["feeding_setup"])
    if setup != "Normal":
        alerts.append(setup.upper())
    return alerts


def _meal_roster(boarders, meal, care_date, holiday_hours=False):
    """Return dogs that need this meal under the selected day's operating hours."""
    required_col = f"{meal.lower()}_required"
    dogs = boarders[boarders[required_col].astype(int) == 1].copy()
    if meal != "Dinner" or care_date.weekday() >= 5 or holiday_hours:
        return dogs

    checkout = pd.to_datetime(
        dogs["actual_checkout_datetime"].combine_first(dogs["planned_checkout_datetime"]),
        errors="coerce",
    )
    return dogs[checkout.dt.date != care_date].copy()


def _meal_dashboard(boarders, feedings, medications, care_date, employee, holiday_hours=False):
    _show_stamp_confirmation()
    toolbar = st.container(key="boarding_toolbar").columns([1.45, 1.8, 1.15])
    meal = toolbar[0].radio("Meal", MEALS, horizontal=True, key="boarding_meal")
    search = toolbar[1].text_input(
        "Search", placeholder="Search dog or room", key="boarding_meal_search"
    ).strip().lower()
    status_filter = toolbar[2].selectbox(
        "Status", ("All statuses", "Needs action", "In progress", "Complete"),
        key="boarding_meal_status",
    )
    med_col = f"{meal.lower()}_med_required"
    dogs = _meal_roster(boarders, meal, care_date, holiday_hours)
    eligible_stays = set(dogs["boarding_stay_id"].astype(int))
    records = (
        feedings[
            (feedings["meal"] == meal)
            & (feedings["boarding_stay_id"].astype(int).isin(eligible_stays))
        ]
        if not feedings.empty else feedings
    )
    placed = int(records["placed_at"].notna().sum()) if not records.empty else 0
    evaluated = int(records["picked_up_at"].notna().sum()) if not records.empty else 0
    meds_needed = int(dogs[med_col].astype(int).sum())
    med_done = int((
        (medications["meal"] == meal)
        & (medications["boarding_stay_id"].astype(int).isin(eligible_stays))
    ).sum()) if not medications.empty else 0

    st.markdown(f"## {meal}")
    if meal == "Dinner" and care_date.weekday() < 5 and not holiday_hours:
        st.caption("Dogs departing today are hidden from dinner during normal weekday hours.")
    st.markdown(
        f"""<div class="boarding-progress-strip">
            <div><strong>{placed}/{len(dogs)}</strong><span>Food placed</span></div>
            <div><strong>{evaluated}/{len(dogs)}</strong><span>Bowls evaluated</span></div>
            <div><strong>{med_done}/{meds_needed}</strong><span>Medication checks</span></div>
            <div><strong>{len(dogs) - evaluated}</strong><span>Awaiting completion</span></div>
        </div>""",
        unsafe_allow_html=True,
    )
    if dogs.empty:
        st.info(f"No boarding dogs require {meal.lower()} on this date. Configure meal schedules under Stay Setup.")
        return

    def state(row):
        record = _record_for(feedings, int(row["boarding_stay_id"]), meal)
        if record is None or pd.isna(record["placed_at"]): return 0
        if pd.isna(record["picked_up_at"]): return 1
        return 2
    dogs["care_state"] = dogs.apply(state, axis=1)
    def operation_status(row):
        care_state = int(row["care_state"])
        if care_state == 0:
            return "Needs action"
        if care_state == 1:
            return "In progress"
        if bool(row[med_col]) and _record_for(
            medications, int(row["boarding_stay_id"]), meal
        ) is None:
            return "Needs action"
        return "Complete"

    dogs["operation_status"] = dogs.apply(operation_status, axis=1)
    if search:
        room_text = dogs.apply(_room, axis=1).astype(str).str.lower()
        dogs = dogs[
            dogs["dog_name"].astype(str).str.lower().str.contains(search, regex=False)
            | room_text.str.contains(search, regex=False)
        ].copy()
    if status_filter != "All statuses":
        dogs = dogs[dogs["operation_status"] == status_filter].copy()
    if dogs.empty:
        st.info("No boarding dogs match these filters.")
        return
    dogs["meal_room_section"] = dogs.apply(
        lambda row: room_section(row.to_dict()) or "Other", axis=1,
    )
    dogs["meal_room_order"] = dogs["meal_room_section"].map(
        {section: index for index, section in enumerate(MEAL_ROOM_ORDER)}
    ).fillna(len(MEAL_ROOM_ORDER)).astype(int)
    dogs["room_sort_number"] = pd.to_numeric(dogs["room_number"], errors="coerce")
    dogs = dogs.sort_values(
        ["meal_room_order", "care_state", "room_sort_number", "room_number", "dog_name"],
        na_position="last",
    )

    def render_dog(dog):
        stay_id = int(dog["boarding_stay_id"])
        record = _record_for(feedings, stay_id, meal)
        med_record = _record_for(medications, stay_id, meal)
        title = f"{dog['dog_name']} — {_room(dog)}"
        row_token = f"{care_date}_{meal}_{stay_id}"
        expanded = st.session_state.pop("boarding_open_row", None) == row_token
        alerts = _alerts(dog)
        instruction = (
            alerts[0] if alerts
            else str(dog.get("food_label") or dog.get("feeding_tricks") or "No special instructions")
        )
        status = str(dog["operation_status"])
        if status == "Complete":
            status_label, status_class = "Complete", "complete"
        elif int(dog["care_state"]) == 1:
            status_label, status_class = "Bowl waiting", "waiting"
        elif int(dog["care_state"]) == 2:
            status_label, status_class = "Medication due", "medication"
        else:
            status_label, status_class = "Food needed", "needed"

        with st.container(key=f"boarding_row_{care_date}_{meal}_{stay_id}"):
            name_col, instruction_col, status_col, action_col = st.columns(
                [2.0, 3.1, 1.35, 1.55], vertical_alignment="center"
            )
            name_col.markdown(
                f"**{dog['dog_name']}**  \n<small>{_room(dog)}</small>",
                unsafe_allow_html=True,
            )
            instruction_col.caption(instruction)
            status_col.markdown(
                f'<span class="boarding-status boarding-status--{status_class}">{status_label}</span>',
                unsafe_allow_html=True,
            )
            if int(dog["care_state"]) == 0:
                if action_col.button(
                    "Place food", key=f"row_place_{care_date}_{meal}_{stay_id}",
                    use_container_width=True, disabled=not employee,
                ):
                    place_food(stay_id, care_date, meal, employee)
                    _queue_stamp_confirmation(
                        employee, str(dog["dog_name"]), f"{meal} food placed"
                    )
                    st.rerun()
            else:
                action_label = "Record appetite" if int(dog["care_state"]) == 1 else (
                    "Confirm meds" if status_label == "Medication due" else "View details"
                )
                if action_col.button(
                    action_label, key=f"row_open_{care_date}_{meal}_{stay_id}",
                    use_container_width=True,
                ):
                    st.session_state["boarding_open_row"] = row_token
                    st.rerun()

        if expanded:
            if st.button(
                "Close details", key=f"row_close_{care_date}_{meal}_{stay_id}"
            ):
                st.rerun()
            badges = _alerts(dog)
            if badges:
                st.error("  •  ".join(badges))
            if dog["food_label"]:
                st.markdown(f"**Food label:** {dog['food_label']}")
            if dog["feeding_tricks"]:
                st.info(f"Feeding tricks: {dog['feeding_tricks']}")

            if record is None or pd.isna(record["placed_at"]):
                st.warning("Food not placed. Use the Place food action in the roster row.")
            elif pd.isna(record["picked_up_at"]):
                st.success(f"Food placed by {record['placed_by']} at {_stamp(record['placed_at'])}")
                with st.form(f"pickup_{care_date}_{meal}_{stay_id}"):
                    appetite = st.radio("Appetite", ("None", "Some", "All"), horizontal=True)
                    note = st.text_area("Meal note (optional)", max_chars=500)
                    if st.form_submit_button(
                        "Pick up bowl and stamp appetite", use_container_width=True,
                        disabled=not employee,
                    ):
                        try:
                            pick_up_bowl(stay_id, care_date, meal, employee, appetite, note)
                            _queue_stamp_confirmation(
                                employee, str(dog["dog_name"]),
                                f"{meal} bowl picked up · Ate {appetite.lower()}",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.warning(str(exc))
            else:
                st.success(
                    f"Food placed by {record['placed_by']} at {_stamp(record['placed_at'])} · "
                    f"Bowl picked up by {record['picked_up_by']} at {_stamp(record['picked_up_at'])} · "
                    f"Appetite: {record['appetite']}"
                )
                if record.get("meal_note"):
                    st.caption(str(record["meal_note"]))

            if bool(dog[med_col]):
                st.divider()
                st.markdown("**Medication check required**")
                if dog["medication_tips"]:
                    st.info(f"Medication tip: {dog['medication_tips']}")
                if med_record is not None:
                    st.success(
                        f"Medication: {med_record['result']} by "
                        f"{med_record['employee_initials']} at {_stamp(med_record['completed_at'])}"
                    )
                    if med_record.get("administration_note"):
                        st.caption(str(med_record["administration_note"]))
                else:
                    with st.form(f"med_{care_date}_{meal}_{stay_id}"):
                        result = st.radio("Result", ("Given", "Not given"), horizontal=True)
                        med_note = st.text_input(
                            "Method or note", placeholder="Pill pocket worked / Had to pill"
                        )
                        if st.form_submit_button(
                            "Confirm medication", use_container_width=True,
                            disabled=not employee,
                        ):
                            try:
                                confirm_medication(
                                    stay_id, care_date, meal, employee, result, med_note
                                )
                                _queue_stamp_confirmation(
                                    employee, str(dog["dog_name"]),
                                    f"{meal} medication {result.lower()}",
                                )
                                st.rerun()
                            except Exception:
                                st.warning(
                                    "This medication check was already confirmed on another phone. Refreshing…"
                                )
                                st.rerun()

    for section in MEAL_ROOM_ORDER:
        section_dogs = dogs[dogs["meal_room_section"] == section]
        if section_dogs.empty:
            continue
        st.markdown(
            f'<div class="boarding-room-heading"><span>{MEAL_ROOM_LABELS[section]}</span>'
            f'<strong>{len(section_dogs)} dog{"s" if len(section_dogs) != 1 else ""}</strong></div>',
            unsafe_allow_html=True,
        )
        for _, dog in section_dogs.iterrows():
            render_dog(dog)


def _stay_setup(boarders, can_edit=True):
    if boarders.empty:
        st.info("No boarding stays cover this date."); return
    options = {int(row["boarding_stay_id"]): f"{row['dog_name']} — {_room(row)}" for _, row in boarders.iterrows()}
    stay_id = st.selectbox("Boarding dog", list(options), format_func=options.get)
    row = boarders[boarders["boarding_stay_id"] == stay_id].iloc[0]
    has_sibling = _has_boarding_sibling(boarders, row)
    with st.form(f"profile_{stay_id}"):
        st.markdown("#### Required meals")
        c1, c2, c3 = st.columns(3)
        breakfast = c1.checkbox("Breakfast", bool(row["breakfast_required"]))
        lunch = c2.checkbox("Lunch", bool(row["lunch_required"]))
        dinner = c3.checkbox("Dinner", bool(row["dinner_required"]))
        st.markdown("#### Medication checks due with meal")
        m1, m2, m3 = st.columns(3)
        breakfast_med = m1.checkbox("Breakfast medication", bool(row["breakfast_med_required"]))
        lunch_med = m2.checkbox("Lunch medication", bool(row["lunch_med_required"]))
        dinner_med = m3.checkbox("Dinner medication", bool(row["dinner_med_required"]))
        feeding_tricks = st.text_area("Feeding tricks", value=str(row["feeding_tricks"]), max_chars=500)
        medication_tips = st.text_area("Medication tips", value=str(row["medication_tips"]), max_chars=500)
        food_label = st.text_input("Food label", value=str(row["food_label"]), max_chars=200, placeholder="Blue container / Bag labeled Bella")
        allergy_status = st.selectbox("Allergies", ("Not recorded", "No known allergies", "Allergy alert"), index=("Not recorded", "No known allergies", "Allergy alert").index(str(row["allergy_status"])))
        allergy_details = st.text_input("Allergy details", value=str(row["allergy_details"]), max_chars=500)
        if has_sibling:
            st.markdown("#### Sibling feeding setup")
            feeding_setup = st.selectbox("Feeding setup", ("Normal", "Supervise feeding", "Feed separately"), index=("Normal", "Supervise feeding", "Feed separately").index(str(row["feeding_setup"])))
            different_food = st.checkbox("Different food from sibling/roommate", bool(row["different_food_alert"]))
        else:
            feeding_setup = "Normal"
            different_food = False
        if st.form_submit_button(
            "Save stay care setup", use_container_width=True, disabled=not can_edit
        ):
            save_care_profile(stay_id, {
                "breakfast_required": breakfast, "lunch_required": lunch, "dinner_required": dinner,
                "breakfast_med_required": breakfast_med, "lunch_med_required": lunch_med, "dinner_med_required": dinner_med,
                "feeding_tricks": feeding_tricks, "medication_tips": medication_tips,
                "allergy_status": allergy_status, "allergy_details": allergy_details,
                "food_label": food_label, "different_food_alert": different_food, "feeding_setup": feeding_setup,
            }); st.success("Boarding care setup saved."); st.rerun()


def _history(boarders, employee):
    if boarders.empty: st.info("No boarding dogs available."); return
    options = {int(row["boarding_stay_id"]): f"{row['dog_name']} — {_room(row)}" for _, row in boarders.iterrows()}
    stay_id = st.selectbox("Dog and stay", list(options), format_func=options.get, key="history_stay")
    with st.form("stay_note"):
        note = st.text_area("Add a boarding note", max_chars=1000)
        if st.form_submit_button("Stamp note", disabled=not employee):
            if note.strip(): add_boarding_note(stay_id, employee, note); st.rerun()
    feedings, meds, notes = load_stay_history(stay_id)
    st.markdown("#### Feedings")
    feeding_display = _feeding_history_table(feedings)
    if feeding_display.empty:
        st.info("No feeding history has been recorded for this stay.")
    else:
        st.dataframe(
            feeding_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Meal": st.column_config.TextColumn(width="small"),
                "Food Placed": st.column_config.TextColumn(width="medium"),
                "Bowl Picked Up": st.column_config.TextColumn(width="medium"),
                "Appetite": st.column_config.TextColumn(width="small"),
                "Notes": st.column_config.TextColumn(width="large"),
            },
        )
    st.markdown("#### Medication checks")
    medication_display = _medication_history_table(meds)
    if medication_display.empty:
        st.info("No medication checks have been recorded for this stay.")
    else:
        st.dataframe(
            medication_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Meal": st.column_config.TextColumn(width="small"),
                "Result": st.column_config.TextColumn(width="small"),
                "Completed By": st.column_config.TextColumn(width="small"),
                "Time": st.column_config.TextColumn(width="small"),
                "Notes": st.column_config.TextColumn(width="large"),
            },
        )
    st.markdown("#### Boarding notes")
    note_display = _note_history_table(notes)
    if note_display.empty:
        st.info("No boarding notes have been added for this stay.")
    else:
        st.dataframe(
            note_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date": st.column_config.TextColumn(width="small"),
                "Time": st.column_config.TextColumn(width="small"),
                "Added By": st.column_config.TextColumn(width="small"),
                "Note": st.column_config.TextColumn(width="large"),
            },
        )


def _roll_call(boarders, roll_date):
    st.metric("Expected overnight", len(boarders))
    rows = "".join(
        f"<tr><td>☐</td><td>{escape(str(row['dog_name']))}</td><td>{escape(_room(row))}</td><td>{escape(' • '.join(_alerts(row)))}</td></tr>"
        for _, row in boarders.iterrows()
    )
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Boarding Roll Call</title>
    <style>body{{font-family:Arial;margin:32px}}h1{{margin-bottom:4px}}table{{width:100%;border-collapse:collapse;font-size:18px}}td,th{{padding:12px;border-bottom:1px solid #bbb;text-align:left}}.sign{{margin-top:35px;line-height:2.5}}</style></head><body>
    <h1>Planet Bark — Nightly Boarding Roll Call</h1><p>{roll_date:%m/%d/%Y}</p>
    <h2>Expected overnight: {len(boarders)} dogs</h2><table><tr><th></th><th>Dog</th><th>Room</th><th>Safety alerts</th></tr>{rows}</table>
    <div class='sign'>Physical count: ______ &nbsp; Counted by: ______ &nbsp; Second check: ______<br>Printed: {datetime.now():%m/%d/%Y %I:%M %p}</div></body></html>"""
    st.download_button("Download printable roll call", html, file_name=f"boarding-roll-call-{roll_date}.html", mime="text/html", use_container_width=True)
    for _, row in boarders.iterrows():
        st.write(f"☐ **{row['dog_name']}** — {_room(row)}")


def show_boarding_care():
    st.title("Boarding Care")
    st.caption("Shared live feeding, medication, notes, and overnight accountability")
    user = current_user()
    today = date.today()
    try:
        user_shifts = load_shifts(today, today, user_id=user["user_id"]) if user else None
        can_edit = _can_edit_boarding(user, user_shifts)
    except Exception:
        can_edit = user is not None and user.get("role") in ("Developer", "Boss")
    if can_edit:
        employee = _employee_picker()
    else:
        employee = ""
        st.info(
            "View only — you can stamp and save Boarding Care entries while you are working your scheduled shift."
        )
    if st_autorefresh is not None:
        st_autorefresh(interval=8000, limit=None, key="boarding_live_refresh")
        st.caption("Live updates refresh every 8 seconds.")
    elif st.button("Refresh shared status", use_container_width=True):
        st.rerun()
    care_date = st.date_input("Care date", value=date.today(), format="MM/DD/YYYY", key="boarding_care_date")
    try:
        boarders, feedings, medications = load_boarding_care(care_date)
    except Exception as exc:
        st.error("Boarding Care database tables are not ready. Run migration 011_boarding_care.sql.")
        st.exception(exc)
        return
    holiday_hours, _ = is_schedule_holiday(care_date)
    can_manage_stays = user["role"] in ("Developer", "Boss", "Cross-Trained", "Office")
    tab_names = ["Today / Feeding", "Entire Stay", "Nightly Roll Call"]
    if can_manage_stays:
        tab_names.insert(1, "Stay Setup")
    selected_view = st.segmented_control(
        "Boarding Care section",
        tab_names,
        default=tab_names[0],
        key="boarding_care_section",
        label_visibility="collapsed",
        width="stretch",
    ) or tab_names[0]

    # Render only the selected section. Streamlit tabs render every hidden tab,
    # which made Boarding Care rebuild forms and query stay history each rerun.
    if selected_view == "Today / Feeding":
        _meal_dashboard(
            boarders, feedings, medications, care_date, employee, holiday_hours
        )
    elif selected_view == "Stay Setup":
        _stay_setup(boarders, can_edit)
    elif selected_view == "Entire Stay":
        _history(boarders, employee)
    else:
        _roll_call(boarders, care_date)
