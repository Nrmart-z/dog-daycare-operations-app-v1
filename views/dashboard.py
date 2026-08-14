import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import streamlit as st

from database import (
    load_dogs, load_rooms, load_todays_assignments,
    load_todays_boarding_movements,
)
from room_capacity import remaining_space_tables


DAYCARE_LATITUDE = 41.741425
DAYCARE_LONGITUDE = -72.719780
DAYCARE_TIMEZONE = ZoneInfo("America/New_York")
HIGH_ATTENDANCE_THRESHOLD = 65
COMFORTABLE_CAPACITY_MAX = 64
STANDARD_MAXIMUM_CAPACITY = 85
OVERFLOW_ROOM_NUMBERS = ("5", "27", "28", "29", "59")


WEATHER_DESCRIPTIONS = {
    0: "Clear",
    1: "Mostly Clear",
    2: "Partly Cloudy",
    3: "Cloudy",
    45: "Foggy",
    48: "Freezing Fog",
    51: "Light Drizzle",
    53: "Drizzle",
    55: "Heavy Drizzle",
    56: "Freezing Drizzle",
    57: "Heavy Freezing Drizzle",
    61: "Light Rain",
    63: "Rain",
    65: "Heavy Rain",
    66: "Freezing Rain",
    67: "Heavy Freezing Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Light Showers",
    81: "Showers",
    82: "Heavy Showers",
    85: "Snow Showers",
    86: "Heavy Snow Showers",
    95: "Thunderstorms",
    96: "Thunderstorms with Hail",
    99: "Severe Thunderstorms with Hail"
}


WEATHER_ICONS = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌦️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",
    73: "❄️",
    75: "❄️",
    77: "❄️",
    80: "🌦️",
    81: "🌧️",
    82: "🌧️",
    85: "🌨️",
    86: "🌨️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️"
}


@st.cache_data(ttl=1200, show_spinner=False)
def load_dashboard_weather():

    parameters = urlencode(
        {
            "latitude": DAYCARE_LATITUDE,
            "longitude": DAYCARE_LONGITUDE,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "fahrenheit",
            "timezone": "America/New_York",
            "forecast_days": 1
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{parameters}"

    with urlopen(url, timeout=5) as response:
        data = json.load(response)

    current = data["current"]
    daily = data["daily"]
    weather_code = int(current["weather_code"])

    return {
        "temperature": round(float(current["temperature_2m"])),
        "high": round(float(daily["temperature_2m_max"][0])),
        "low": round(float(daily["temperature_2m_min"][0])),
        "description": WEATHER_DESCRIPTIONS.get(
            weather_code,
            "Current Conditions"
        ),
        "icon": WEATHER_ICONS.get(weather_code, "🌡️")
    }


@st.fragment(run_every="60s")
def show_dashboard_clock_and_weather(show_date_time=True, show_weather=True):

    now = datetime.now(DAYCARE_TIMEZONE)
    time_text = now.strftime("%I:%M %p").lstrip("0")

    try:
        weather = load_dashboard_weather()
    except Exception:
        weather = None

    status_bar = st.container(border=True)

    with status_bar:
        if show_date_time and show_weather:
            date_column, time_column, weather_column = st.columns(3)
        elif show_date_time:
            date_column, time_column = st.columns(2)
            weather_column = None
        else:
            weather_column = st.container()

        if show_date_time:
            date_column.markdown(
                f"""
                <div class="dashboard-status-item dashboard-status-item--date">
                    <span class="dashboard-status-icon">&#128197;</span>
                    <span class="dashboard-status-label">TODAY</span>
                    <strong>{now.strftime('%m/%d/%Y')}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )
            time_column.markdown(
                f"""
                <div class="dashboard-status-item dashboard-status-item--time">
                    <span class="dashboard-status-icon">&#128339;</span>
                    <span class="dashboard-status-label">TIME</span>
                    <strong>{time_text}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )
        if show_weather and weather:
            weather_column.markdown(
                f"""
                <div class="dashboard-status-item dashboard-status-item--weather">
                    <span class="dashboard-status-icon">&#9728;&#65039;</span>
                    <span class="dashboard-status-label">
                        WEST HARTFORD WEATHER
                    </span>
                    <strong>
                        {weather['icon']} {weather['temperature']}°F ·
                        {weather['description']}
                    </strong>
                    <small>
                        High {weather['high']}° · Low {weather['low']}°
                    </small>
                </div>
                """,
                unsafe_allow_html=True
            )
        elif show_weather:
            weather_column.markdown(
                """
                <div class="dashboard-status-item dashboard-status-item--weather">
                    <span class="dashboard-status-icon">&#127780;&#65039;</span>
                    <span class="dashboard-status-label">
                        WEST HARTFORD WEATHER
                    </span>
                    <strong>Weather temporarily unavailable</strong>
                </div>
                """,
                unsafe_allow_html=True
            )

        if show_weather:
            st.caption("Weather for ZIP code 06110 · Open-Meteo")


def show_checklist_item(label, detail, status):

    status_styles = {
        "complete": ("&#10003;", "#2e7d32", "rgba(76, 175, 80, 0.12)"),
        "attention": ("!", "#b42318", "rgba(237, 50, 35, 0.12)"),
        "pending": ("&#8226;", "#8a6100", "rgba(255, 193, 7, 0.14)")
    }
    icon, color, background = status_styles[status]

    st.markdown(
        f"""
        <div class="dashboard-checklist-item"
             style="background:{background}; border-color:{color};">
            <span class="dashboard-checklist-icon"
                  style="background:{color};">{icon}</span>
            <span class="dashboard-checklist-copy">
                <strong>{label}</strong>
                <small>{detail}</small>
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )


def show_dashboard():

    show_dashboard_clock_and_weather(show_date_time=False)

    st.write("")

    # =============================================
    # Load Dashboard Data
    # =============================================

    dogs_df = load_dogs()
    rooms_df = load_rooms()
    assignments_df = load_todays_assignments()
    arrivals_df, departures_df = load_todays_boarding_movements()

    dogs_checked_in = len(dogs_df)
    boarding_count = int(dogs_df["boarding_status"].sum())
    daycare_count = dogs_checked_in - boarding_count
    if st.session_state.get("assignment_draft") is not None:
        assignment_status = "Draft"
    elif not assignments_df.empty:
        assignment_status = "Finalized"
    else:
        assignment_status = "TBD"

    attendance_dog_ids = set(dogs_df["dog_id"].astype(int))
    saved_assignment_dog_ids = set(assignments_df["dog_id"].astype(int))
    draft = st.session_state.get("assignment_draft")
    draft_assignment_dog_ids = {
        int(assignment["dog_id"])
        for assignment in (draft or [])
    }
    current_assignment_dog_ids = (
        draft_assignment_dog_ids
        if draft is not None
        else saved_assignment_dog_ids
    )
    unassigned_count = (
        len(st.session_state.get("assignment_unassigned", []))
        if draft is not None
        else len(attendance_dog_ids - saved_assignment_dog_ids)
    )
    open_room_ids = set(
        rooms_df.loc[rooms_df["status"] == 1, "room_id"].astype(int)
    )
    boarders_df = dogs_df[dogs_df["boarding_status"] == 1]
    boarding_rooms_ready = bool(
        boarders_df["assigned_room_id"].notna().all()
        and all(
            int(room_id) in open_room_ids
            for room_id in boarders_df["assigned_room_id"].dropna()
        )
    )
    attendance_matches_assignments = (
        attendance_dog_ids == saved_assignment_dog_ids
    )
    normalized_room_numbers = rooms_df["room_number"].map(
        lambda value: str(value).strip().removesuffix(".0")
    )
    closed_overflow_rooms_df = rooms_df[
        normalized_room_numbers.isin(OVERFLOW_ROOM_NUMBERS)
        & (rooms_df["status"].fillna(0).astype(int) == 0)
    ].copy()
    closed_overflow_rooms_df["overflow_order"] = (
        closed_overflow_rooms_df["room_number"].map(
            lambda value: OVERFLOW_ROOM_NUMBERS.index(
                str(value).strip().removesuffix(".0")
            )
        )
    )
    closed_overflow_rooms_df = closed_overflow_rooms_df.sort_values(
        "overflow_order"
    )
    closed_overflow_room_numbers = [
        str(value).strip().removesuffix(".0")
        for value in closed_overflow_rooms_df["room_number"]
    ]
    needs_overflow_review = (
        dogs_checked_in >= HIGH_ATTENDANCE_THRESHOLD
        or unassigned_count > 0
    )

    # =============================================
    # Header
    # =============================================

    st.title("Dashboard")
    st.caption("Planet Bark Nap Time Assignment System")

    st.write("")

    # =============================================
    # Today's Summary
    # =============================================

    summary = st.container(border=True)

    with summary:

        st.subheader("Today's Summary", anchor=False)

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Total Dogs",
                dogs_checked_in
            )

        with col2:
            st.metric(
                "Daycare",
                daycare_count
            )

        with col3:
            st.metric(
                "Boarding",
                boarding_count
            )

        with col4:
            st.metric(
                "Assignments",
                assignment_status
            )

        st.caption(
            "Comfortable operating capacity: up to 64 dogs · "
            "Standard maximum capacity: 85 dogs"
        )

        if dogs_checked_in >= STANDARD_MAXIMUM_CAPACITY:
            st.error(
                f"Maximum-capacity alert: {dogs_checked_in} dogs are "
                "present. The standard maximum is 85 dogs. Review every "
                "assignment and available overflow room before accepting "
                "additional dogs."
            )
        elif dogs_checked_in >= HIGH_ATTENDANCE_THRESHOLD:
            st.warning(
                f"High-capacity warning: {dogs_checked_in} dogs are "
                "present. Comfortable operation is up to "
                f"{COMFORTABLE_CAPACITY_MAX}; the standard maximum is "
                f"{STANDARD_MAXIMUM_CAPACITY}. Review overflow rooms and "
                "generate assignments early."
            )

        st.markdown("#### Daily Checklist")
        checklist_left, checklist_right = st.columns(2)

        with checklist_left:
            show_checklist_item(
                "Attendance ready",
                (
                    f"{dogs_checked_in} dogs are on today's attendance."
                    if dogs_checked_in
                    else "No dogs have been checked in yet."
                ),
                "complete" if dogs_checked_in else "pending"
            )
            show_checklist_item(
                "Boarding rooms confirmed",
                (
                    "No boarding rooms are needed today."
                    if boarders_df.empty
                    else "Every boarder has an open boarding room."
                    if boarding_rooms_ready
                    else "A boarder needs an available room."
                ),
                "complete" if boarding_rooms_ready else "attention"
            )
            show_checklist_item(
                "Assignments generated",
                (
                    "A working assignment draft is ready."
                    if draft is not None
                    else (
                        "Today's finalized assignments are available."
                        if not assignments_df.empty
                        else "Generate today's nap assignments."
                    )
                ),
                (
                    "complete"
                    if draft is not None or not assignments_df.empty
                    else "pending"
                )
            )

        with checklist_right:
            all_dogs_assigned = bool(
                dogs_checked_in
                and attendance_dog_ids == current_assignment_dog_ids
            )
            show_checklist_item(
                "All dogs assigned",
                (
                    "Every dog present has a placement."
                    if all_dogs_assigned
                    else f"{unassigned_count} dogs still need placement."
                ),
                "complete" if all_dogs_assigned else "attention"
            )
            show_checklist_item(
                "Assignments finalized",
                (
                    f"{len(assignments_df)} assignments are saved for today."
                    if assignment_status == "Finalized"
                    else "Review and finalize the assignment draft."
                ),
                (
                    "complete"
                    if assignment_status == "Finalized"
                    else "pending"
                )
            )
            show_checklist_item(
                "Attendance changes synced",
                (
                    "Finalized assignments match current attendance."
                    if assignment_status == "Finalized"
                    and attendance_matches_assignments
                    else (
                        "Attendance changed; update finalized assignments."
                        if assignment_status == "Finalized"
                        else "This check is completed after finalization."
                    )
                ),
                (
                    "complete"
                    if assignment_status == "Finalized"
                    and attendance_matches_assignments
                    else (
                        "attention"
                        if assignment_status == "Finalized"
                        else "pending"
                    )
                )
            )

        st.markdown("#### Nap-Time Space")

        if draft is not None:
            capacity_assignments = draft
            capacity_matches_attendance = (
                attendance_dog_ids == draft_assignment_dog_ids
            )
            capacity_label = (
                "Projected Remaining Spaces"
                if capacity_matches_attendance
                else "Needs Recalculation"
            )
        elif not assignments_df.empty:
            capacity_assignments = assignments_df.to_dict("records")
            capacity_matches_attendance = attendance_matches_assignments
            capacity_label = (
                "Confirmed Remaining Spaces"
                if capacity_matches_attendance
                else "Needs Recalculation"
            )
        else:
            capacity_assignments = None
            capacity_matches_attendance = False
            capacity_label = "Not Calculated Yet"

        st.markdown(f"**{capacity_label}**")

        if capacity_assignments is None:
            st.info(
                "Generate assignments to see which crate sizes and room "
                "areas will remain available."
            )
        else:
            if not capacity_matches_attendance:
                st.warning(
                    "Attendance no longer matches these assignments. "
                    "Regenerate or update the assignments before relying "
                    "on these remaining-space counts."
                )

            crate_space_df, room_space_df = remaining_space_tables(
                capacity_assignments,
                rooms_df
            )
            crate_space_column, room_space_column = st.columns(2)

            with crate_space_column:
                st.caption("Crates Remaining")
                st.dataframe(
                    crate_space_df,
                    hide_index=True,
                    use_container_width=True
                )

            with room_space_column:
                st.caption("Rooms Remaining")
                st.dataframe(
                    room_space_df,
                    hide_index=True,
                    use_container_width=True
                )

            st.caption(
                "Closed rooms are excluded. Siblings sharing one room "
                "count as one occupied space."
            )

    st.write("")

    # =============================================
    # Today's Boarding Arrivals and Departures
    # =============================================

    movements = st.container(border=True)
    with movements:
        st.subheader("Today's Boarding Arrivals & Departures", anchor=False)
        arrivals_column, departures_column = st.columns(2)
        with arrivals_column:
            st.markdown("#### Arrivals")
            if arrivals_df.empty:
                st.info("No boarding arrivals today.")
            else:
                st.dataframe(arrivals_df, hide_index=True, use_container_width=True)
        with departures_column:
            st.markdown("#### Departures")
            if departures_df.empty:
                st.info("No boarding departures today.")
            else:
                st.dataframe(departures_df, hide_index=True, use_container_width=True)

    st.write("")

    # =============================================
    # Bottom Section
    # =============================================

    left, right = st.columns([2, 1])

    # ---------------------------------------------
    # Activity
    # ---------------------------------------------

    with left:

        activity = st.container(border=True)

        with activity:

            st.subheader(
                "Today's Activity",
                anchor=False
            )

            if (
                assignment_status == "Finalized"
                and attendance_matches_assignments
            ):
                st.success(
                    "Today's assignments are finalized and match attendance."
                )
            elif assignment_status == "Finalized":
                st.warning(
                    "Attendance changed after finalization. Open Assignments "
                    "to review and save an updated revision."
                )
            elif assignment_status == "Draft":
                st.info(
                    f"Assignment draft is ready with {unassigned_count} "
                    "unassigned dogs."
                )
            else:
                st.info("Today's assignments have not been generated.")

            if needs_overflow_review:
                if closed_overflow_room_numbers:
                    petite_room = (
                        ["Room 5"]
                        if "5" in closed_overflow_room_numbers
                        else []
                    )
                    back_hall_rooms = [
                        room_number
                        for room_number in closed_overflow_room_numbers
                        if room_number in {"27", "28", "29"}
                    ]
                    recommendation_parts = petite_room

                    crate_room = (
                        ["Crate Room 59"]
                        if "59" in closed_overflow_room_numbers
                        else []
                    )

                    if back_hall_rooms:
                        recommendation_parts.append(
                            "Back Hall " + ", ".join(back_hall_rooms)
                        )

                    recommendation_parts.extend(crate_room)

                    review_reason = (
                        f"High attendance review: {dogs_checked_in} dogs are "
                        "present."
                        if dogs_checked_in >= HIGH_ATTENDANCE_THRESHOLD
                        else f"Space review: {unassigned_count} dogs still "
                        "need placement."
                    )
                    st.warning(
                        review_reason + " Consider opening "
                        + " and ".join(recommendation_parts)
                        + " if more nap-time space is needed."
                    )

                    if st.button(
                        "Review Rooms in Room Management",
                        key="dashboard_review_overflow_rooms",
                        use_container_width=True
                    ):
                        st.session_state.page = "Room Management"
                        st.rerun()
                else:
                    st.success(
                        "The overflow rooms used for high-attendance days "
                        "are already available."
                    )

    # ---------------------------------------------
    # Quick Actions
    # ---------------------------------------------

    with right:

        actions = st.container(border=True)

        with actions:

            st.subheader(
                "Quick Actions",
                anchor=False
            )

            if st.button(
                "Generate Assignments",
                key="dashboard_generate",
                use_container_width=True
            ):
                st.session_state.page = "Assignments"
                st.rerun()

            if st.button(
                "Attendance",
                key="dashboard_attendance",
                use_container_width=True
            ):
                st.session_state.page = "Attendance"
                st.rerun()

            if st.button(
                "Daily Records",
                key="dashboard_records",
                use_container_width=True
            ):
                st.session_state.page = "Daily Records"
                st.rerun()
