import pandas as pd
import streamlit as st
from datetime import date, datetime, time, timedelta

from boarding import (
    format_room_option,
    get_eligible_boarding_rooms,
    get_fence_fighter_blocked_room_ids,
    get_shared_sibling_rooms,
    is_allowed
)
from database import (
    add_attendance_records,
    end_boarding_stays,
    load_dogs,
    load_available_dogs,
    load_rooms,
    load_sibling_group,
    remove_attendance_records,
    switch_daycare_to_boarding,
    update_boarding_stays, load_all_dogs
)
from auth import current_user
from operations_service import create_boarding_reservation, load_boarding_reservations


def highlight_play_group(row):

    play_group = str(row["Play Group"]).strip().lower()

    if play_group == "small":
        background = "background-color: #F8C9DF; color: #4A1830"

    elif play_group == "big":
        background = "background-color: #C9E3FA; color: #123B5C"

    elif play_group == "separate":
        background = "background-color: #F5BBB6; color: #641B15"

    else:
        background = ""

    return [background] * len(row)


def format_attendance_option(row):

    visit_type = (
        "Boarding"
        if row["boarding_status"] == 1
        else "Daycare"
    )

    nickname = str(row.get("dog_nickname", "")).strip()
    nickname_detail = ""

    if nickname.lower() not in {"", "nan", "none"}:
        nickname_detail = f" | Nickname: {nickname}"

    return (
        f'{row["dog_name"]} | {visit_type} | '
        f'{row["play_group"]} | Breed: {row["dog_breed"]}'
        f"{nickname_detail}"
    )


def get_possessive_pronoun(gender):

    normalized_gender = str(gender).strip().upper()

    if normalized_gender in {"F", "FEMALE"}:
        return "her"
    if normalized_gender in {"M", "MALE"}:
        return "his"
    return "their"


def get_sibling_relationship(gender):

    normalized_gender = str(gender).strip().upper()

    if normalized_gender in {"F", "FEMALE"}:
        return "sister"
    if normalized_gender in {"M", "MALE"}:
        return "brother"
    return "sibling"


def checkout_time_options(extra_time=None):

    options = [
        time(hour, minute)
        for hour in range(24)
        for minute in (0, 15, 30, 45)
    ]

    if extra_time is not None:
        extra_time = extra_time.replace(second=0, microsecond=0)

        if extra_time not in options:
            options.append(extra_time)

    return sorted(options)


def checkout_window_for_time(value):

    normalized_value = value.replace(second=0, microsecond=0)

    if normalized_value == time(12, 0):
        return "AM"
    if normalized_value == time(19, 0):
        return "PM"
    if normalized_value in {time(23, 59), time(23, 59, 59)}:
        return "TBD"
    return "Special / Late Pickup"


def checkout_time_for_window(window, special_time=None):

    return {
        "AM": time(12, 0),
        "PM": time(19, 0),
        "TBD": time(23, 59, 59),
    }.get(window, special_time or time(19, 0))


def format_normal_time(value):

    return datetime.combine(date.today(), value).strftime(
        "%I:%M %p"
    ).lstrip("0")


def switched_attendance_message(names, destination):

    names = [str(name) for name in names]
    name_list = ", ".join(names)
    verb = "has" if len(names) == 1 else "have"
    return f"{name_list} {verb} been switched to {destination}."


def show_crew_attendance():
    """Read-only daycare and boarding lists for Crew accounts."""
    dogs_df = load_dogs()
    daycare_df = dogs_df[dogs_df["boarding_status"] == 0].copy()
    boarders_df = dogs_df[dogs_df["boarding_status"] == 1].copy()
    st.title("Today's Attendance")
    st.caption("Read-only roster · Dog records and attendance cannot be changed here")

    columns = st.columns(3)
    columns[0].metric("Dogs Present", len(dogs_df))
    columns[1].metric("Daycare", len(daycare_df))
    columns[2].metric("Boarding", len(boarders_df))

    daycare_tab, boarding_tab = st.tabs(["Daycare", "Boarding"])
    with daycare_tab:
        if daycare_df.empty:
            st.info("No daycare dogs are currently checked in.")
        else:
            roster = daycare_df[["dog_name", "dog_breed", "play_group"]].rename(
                columns={
                    "dog_name": "Dog Name",
                    "dog_breed": "Breed",
                    "play_group": "Play Group",
                }
            ).sort_values(["Play Group", "Dog Name"])
            st.dataframe(
                roster.style.apply(highlight_play_group, axis=1),
                use_container_width=True,
                hide_index=True,
            )
    with boarding_tab:
        if boarders_df.empty:
            st.info("No boarding dogs are currently checked in.")
        else:
            boarding_roster = boarders_df[[
                "dog_name", "dog_breed", "assigned_room_number",
                "boarding_check_in", "boarding_check_out", "play_group",
            ]].rename(columns={
                "dog_name": "Dog Name",
                "dog_breed": "Breed",
                "assigned_room_number": "Room Number",
                "boarding_check_in": "Check-In",
                "boarding_check_out": "Check-Out",
                "play_group": "Play Group",
            }).sort_values(["Room Number", "Dog Name"])
            st.dataframe(
                boarding_roster.style.apply(highlight_play_group, axis=1),
                use_container_width=True,
                hide_index=True,
            )


def show_attendance():

    st.title("Attendance")
    st.caption("Manage today's daycare and boarding attendance")

    # =============================================
    # Load Attendance Data
    # =============================================

    dogs_df = load_dogs()
    available_dogs_df = load_available_dogs()
    rooms_df = load_rooms()
    sibling_group_df = load_sibling_group()

    with st.expander("Plan a Future Boarding Arrival"):
        st.caption("Schedule an expected boarding dog before its arrival day.")
        all_dogs_df = load_all_dogs()
        dog_options = {
            int(row.dog_id): f"{row.dog_name} — {row.dog_breed}"
            for _, row in all_dogs_df.iterrows()
        }
        room_options = {
            int(row.room_id): (
                str(row.room_name).strip()
                if str(row.room_name).strip().lower() not in ("", "nan", "none")
                else f"Room {row.room_number}"
            ) for _, row in rooms_df.iterrows()
        }
        with st.form("future_boarding_arrival"):
            planned_dog = st.selectbox("Dog", list(dog_options), format_func=dog_options.get)
            dates = st.columns(2)
            arrival_date = dates[0].date_input("Arrival date", value=date.today() + timedelta(days=1), format="MM/DD/YYYY")
            departure_date = dates[1].date_input("Departure date", value=date.today() + timedelta(days=2), format="MM/DD/YYYY")
            pickup_period = st.radio("Departure pickup", ["AM", "PM"], horizontal=True)
            planned_room = st.selectbox("Room", list(room_options), format_func=room_options.get)
            planned_notes = st.text_input("Notes")
            plan_submitted = st.form_submit_button("Save planned arrival", use_container_width=True)
        if plan_submitted:
            try:
                create_boarding_reservation(
                    planned_dog, arrival_date, departure_date, pickup_period,
                    planned_room, planned_notes, current_user()["user_id"]
                )
                st.success("Future boarding arrival saved."); st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        upcoming = load_boarding_reservations(date.today(), date.today() + timedelta(days=60))
        if not upcoming.empty:
            display = upcoming[["dog_name", "dog_breed", "arrival_date", "departure_date", "pickup_period", "room_name", "room_number"]].copy()
            display["Room"] = display.apply(
                lambda row: row.room_name or f"Room {row.room_number}", axis=1
            )
            st.dataframe(
                display[["dog_name", "dog_breed", "arrival_date", "departure_date", "pickup_period", "Room"]].rename(
                    columns={"dog_name": "Dog Name", "dog_breed": "Breed", "arrival_date": "Arrival",
                             "departure_date": "Departure", "pickup_period": "AM or PM"}
                ), use_container_width=True, hide_index=True
            )

    attendance_notice = st.session_state.pop("attendance_notice", None)

    if attendance_notice:
        st.success(attendance_notice)

    daycare_df = dogs_df[
        dogs_df["boarding_status"] == 0
    ][
        [
            "dog_name",
            "dog_breed",
            "play_group"
        ]
    ].rename(
        columns={
            "dog_name": "Dog Name",
            "dog_breed": "Breed",
            "play_group": "Play Group"
        }
    )

    boarders_df = dogs_df[
        dogs_df["boarding_status"] == 1
    ][
        [
            "dog_name",
            "dog_breed",
            "assigned_room_id",
            "assigned_room_number",
            "boarding_check_in",
            "boarding_check_out",
            "play_group"
        ]
    ].rename(
        columns={
            "dog_name": "Dog Name",
            "dog_breed": "Breed",
            "assigned_room_number": "Room Number",
            "boarding_check_in": "Check-In Date",
            "boarding_check_out": "Check-Out Date",
            "play_group": "Play Group"
        }
    )

    # =============================================
    # Attendance Statistics
    # =============================================

    dogs_present = len(dogs_df)

    daycare_count = len(
        dogs_df[dogs_df["boarding_status"] == 0]
    )

    boarding_count = len(
        dogs_df[dogs_df["boarding_status"] == 1]
    )

    big_group_count = len(
        dogs_df[dogs_df["play_group"] == "Big"]
    )

    small_group_count = len(
        dogs_df[dogs_df["play_group"] == "Small"]
    )

    # =============================================
    # Attendance Summary
    # =============================================

    summary = st.container(border=True)

    with summary:

        st.subheader("Attendance Summary", anchor=False)

        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("Dogs Present", dogs_present)
        col2.metric("Daycare", daycare_count)
        col3.metric("Boarding", boarding_count)
        col4.metric("Big Group", big_group_count)
        col5.metric("Small Group", small_group_count)

    st.write("")

    # =============================================
    # Boarders Table
    # =============================================

    boarders_table = st.container(border=True)

    with boarders_table:

        st.subheader("Today's Boarders", anchor=False)

        if boarders_df.empty:

            st.info("No boarding dogs are present today.")

        else:

            boarders_df["Check-In Date"] = pd.to_datetime(
                boarders_df["Check-In Date"]
            ).dt.strftime("%m/%d/%Y")
            boarders_df["Check-Out Date"] = pd.to_datetime(
                boarders_df["Check-Out Date"]
            ).dt.strftime("%m/%d/%Y")

            room_order = st.radio(
                "Room Order",
                ["Ascending", "Descending"],
                horizontal=True,
                key="boarders_room_order"
            )

            boarders_df = (
                boarders_df
                .sort_values(
                    by=["assigned_room_id", "Dog Name"],
                    ascending=[room_order == "Ascending", True],
                    na_position="last"
                )
                .drop(columns=["assigned_room_id"])
                .reset_index(drop=True)
            )

            st.dataframe(
                boarders_df.style.apply(
                    highlight_play_group,
                    axis=1
                ),
                use_container_width=True,
                hide_index=True
            )

    st.write("")

    # =============================================
    # Daycare Table
    # =============================================

    daycare_table = st.container(border=True)

    with daycare_table:

        st.subheader("Today's Daycare", anchor=False)

        search = st.text_input(
            "Search Daycare Dog",
            placeholder="Search by dog name..."
        )

        filtered_df = daycare_df.copy()

        if search:

            filtered_df = filtered_df[
                filtered_df["Dog Name"].str.contains(
                    search,
                    case=False,
                    na=False
                )
            ]

        play_group_order = {
            "big": 0,
            "small": 1,
            "separate": 2
        }

        filtered_df["_play_group_order"] = (
            filtered_df["Play Group"]
            .astype(str)
            .str.strip()
            .str.lower()
            .map(play_group_order)
            .fillna(3)
        )

        filtered_df["_dog_name_order"] = (
            filtered_df["Dog Name"]
            .astype(str)
            .str.strip()
            .str.lower()
        )

        filtered_df = (
            filtered_df
            .sort_values(
                by=["_play_group_order", "_dog_name_order"]
            )
            .drop(
                columns=["_play_group_order", "_dog_name_order"]
            )
            .reset_index(drop=True)
        )

        st.dataframe(
            filtered_df.style.apply(
                highlight_play_group,
                axis=1
            ),
            use_container_width=True,
            hide_index=True
        )

    st.write("")

    # =============================================
    # Quick Actions
    # =============================================

    actions = st.container(border=True)

    with actions:

        st.subheader("Quick Actions", anchor=False)

        # -----------------------------------------
        # Add Existing Dog to Today's Attendance
        # -----------------------------------------

        with st.expander("Check In Existing Dog"):

            st.caption(
                "Select an Active dog already registered in Dog Management. "
                "Brand-new dog profiles must be created in Dog Management."
            )

            if available_dogs_df.empty:

                st.info("All dogs are already checked in today.")

            else:

                dog_options = {
                    int(row["dog_id"]): (
                        f'{row["dog_name"]} | {row["dog_breed"]}'
                        + (
                            f' | Nickname: {row["dog_nickname"]}'
                            if pd.notna(row["dog_nickname"])
                            and str(row["dog_nickname"]).strip()
                            else ""
                        )
                    )
                    for _, row in available_dogs_df.iterrows()
                }

                visit_type = st.radio(
                    "Visit Type",
                    ["Daycare", "Boarding"],
                    horizontal=True,
                    key="add_attendance_visit_type"
                )

                if visit_type == "Daycare":
                    play_group_filter = st.selectbox(
                        "Filter by Play Group",
                        ["All", "Small", "Separate", "Big"],
                        key="add_daycare_play_group_filter"
                    )
                    filtered_option_ids = set(
                        available_dogs_df.loc[
                            (
                                available_dogs_df["play_group"]
                                == play_group_filter
                            )
                            if play_group_filter != "All"
                            else pd.Series(
                                True,
                                index=available_dogs_df.index
                            ),
                            "dog_id"
                        ].astype(int)
                    )
                    existing_selected_ids = {
                        int(dog_id)
                        for dog_id in st.session_state.get(
                            "add_daycare_dogs", []
                        )
                        if int(dog_id) in dog_options
                    }
                    visible_option_ids = (
                        filtered_option_ids | existing_selected_ids
                    )
                    daycare_dog_options = {
                        dog_id: label
                        for dog_id, label in dog_options.items()
                        if dog_id in visible_option_ids
                    }
                    selected_dog_ids = st.multiselect(
                        "Dogs",
                        options=list(daycare_dog_options),
                        format_func=daycare_dog_options.get,
                        placeholder="Search and select multiple dogs...",
                        key="add_daycare_dogs"
                    )
                    selected_dog_id = None
                    selected_row = None
                else:
                    selected_dog_id = st.selectbox(
                        "Dog",
                        options=list(dog_options),
                        format_func=dog_options.get,
                        key="add_boarding_dog"
                    )
                    selected_dog_ids = [selected_dog_id]
                    selected_row = available_dogs_df[
                        available_dogs_df["dog_id"].astype(int)
                        == selected_dog_id
                    ].iloc[0]

                sibling_rule = None
                sibling_member_ids = []
                sibling_group_id = (
                    selected_row["sibling_group_id"]
                    if selected_row is not None
                    else None
                )

                if pd.notna(sibling_group_id):
                    matching_rules = sibling_group_df[
                        sibling_group_df["sibling_group_id"].astype(int)
                        == int(sibling_group_id)
                    ]

                    if not matching_rules.empty:
                        sibling_rule = matching_rules.iloc[0]
                        sibling_member_ids = [
                            int(sibling_rule[column])
                            for column in (
                                "dog1_id",
                                "dog2_id",
                                "dog3_id",
                                "dog4_id"
                            )
                            if pd.notna(sibling_rule[column])
                            and int(sibling_rule[column]) != selected_dog_id
                        ]

                available_siblings_df = available_dogs_df[
                    available_dogs_df["dog_id"].astype(int).isin(
                        sibling_member_ids
                    )
                ].copy()
                present_siblings_df = dogs_df[
                    dogs_df["dog_id"].astype(int).isin(
                        sibling_member_ids
                    )
                ].copy()
                selected_sibling_ids = []

                if visit_type == "Boarding" and sibling_rule is not None:

                    st.markdown("#### Sibling Group")
                    possessive_pronoun = get_possessive_pronoun(
                        selected_row.get("gender", "")
                    )

                    for _, sibling in present_siblings_df.iterrows():
                        sibling_name = str(sibling["dog_name"])
                        attendance_status = (
                            "Boarding"
                            if sibling["boarding_status"] == 1
                            else "Daycare"
                        )
                        st.info(
                            f"{sibling_name} is already on today's "
                            f"attendance as {attendance_status}."
                        )

                    for _, sibling in available_siblings_df.iterrows():
                        sibling_id = int(sibling["dog_id"])
                        relationship = get_sibling_relationship(
                            sibling.get("gender", "")
                        )
                        add_sibling = st.checkbox(
                            "**Would you like to add "
                            f"{possessive_pronoun} {relationship} "
                            f'{sibling["dog_name"]} too?**',
                            key=(
                                f"add_sibling_{selected_dog_id}_"
                                f"{sibling_id}"
                            )
                        )

                        if add_sibling:
                            selected_sibling_ids.append(sibling_id)

                if visit_type == "Daycare" and selected_dog_ids:
                    selected_id_set = set(selected_dog_ids)
                    prompted_sibling_ids = set()
                    shown_present_ids = set()
                    sibling_prompts = []

                    for primary_id in selected_dog_ids:
                        primary_row = available_dogs_df[
                            available_dogs_df["dog_id"].astype(int)
                            == primary_id
                        ].iloc[0]
                        primary_group_id = primary_row["sibling_group_id"]

                        if pd.isna(primary_group_id):
                            continue

                        matching_rules = sibling_group_df[
                            sibling_group_df["sibling_group_id"].astype(int)
                            == int(primary_group_id)
                        ]

                        if matching_rules.empty:
                            continue

                        primary_rule = matching_rules.iloc[0]
                        group_member_ids = [
                            int(primary_rule[column])
                            for column in (
                                "dog1_id", "dog2_id", "dog3_id", "dog4_id"
                            )
                            if pd.notna(primary_rule[column])
                            and int(primary_rule[column]) != primary_id
                        ]

                        for sibling_id in group_member_ids:
                            if sibling_id in selected_id_set:
                                continue

                            present_match = dogs_df[
                                dogs_df["dog_id"].astype(int) == sibling_id
                            ]
                            if not present_match.empty:
                                if sibling_id not in shown_present_ids:
                                    sibling = present_match.iloc[0]
                                    attendance_status = (
                                        "Boarding"
                                        if sibling["boarding_status"] == 1
                                        else "Daycare"
                                    )
                                    st.info(
                                        f'{sibling["dog_name"]} is already '
                                        "on today's attendance as "
                                        f"{attendance_status}."
                                    )
                                    shown_present_ids.add(sibling_id)
                                continue

                            sibling_match = available_dogs_df[
                                available_dogs_df["dog_id"].astype(int)
                                == sibling_id
                            ]
                            if (
                                sibling_match.empty
                                or sibling_id in prompted_sibling_ids
                            ):
                                continue

                            sibling_prompts.append(
                                (primary_row, sibling_match.iloc[0])
                            )
                            prompted_sibling_ids.add(sibling_id)

                    if sibling_prompts:
                        st.markdown("#### Sibling Groups")

                    for primary_row, sibling in sibling_prompts:
                        sibling_id = int(sibling["dog_id"])
                        relationship = get_sibling_relationship(
                            sibling.get("gender", "")
                        )
                        add_sibling = st.checkbox(
                            "**Would you like to add "
                            f'{get_possessive_pronoun(primary_row.get("gender", ""))} '
                            f'{relationship} {sibling["dog_name"]} too?**',
                            key=(
                                "bulk_daycare_sibling_"
                                f'{int(primary_row["dog_id"])}_{sibling_id}'
                            )
                        )
                        if add_sibling:
                            selected_sibling_ids.append(sibling_id)

                records_to_add = []
                can_add = True

                if visit_type == "Daycare":

                    daycare_dog_ids = list(dict.fromkeys(
                        [*selected_dog_ids, *selected_sibling_ids]
                    ))
                    records_to_add = [
                        {
                            "dog_id": dog_id,
                            "visit_type": "Daycare",
                            "assigned_room_id": None
                        }
                        for dog_id in daycare_dog_ids
                    ]
                    if not records_to_add:
                        can_add = False

                else:

                    st.markdown("#### Boarding Requirements")

                    st.caption(
                        "Check-in date and time will be recorded "
                        "automatically when the dog is added."
                    )
                    stay_columns = st.columns(2)
                    boarding_check_out_date = stay_columns[0].date_input(
                        "Check-Out Date",
                        value=date.today() + timedelta(days=1),
                        min_value=date.today(),
                        format="MM/DD/YYYY",
                        key="new_boarding_check_out_date"
                    )
                    checkout_window = stay_columns[1].selectbox(
                        "Expected Pick-Up",
                        ["AM", "PM", "TBD", "Special / Late Pickup"],
                        help=(
                            "AM uses noon, PM uses 7:00 PM, and TBD keeps "
                            "the stay active through the checkout date."
                        ),
                        key="new_boarding_checkout_window"
                    )
                    special_checkout_time = None
                    if checkout_window == "Special / Late Pickup":
                        available_checkout_times = checkout_time_options()
                        special_checkout_time = st.selectbox(
                            "Special Pick-Up Time",
                            options=available_checkout_times,
                            index=available_checkout_times.index(time(19, 0)),
                            format_func=format_normal_time,
                            key="new_boarding_special_checkout_time"
                        )
                    boarding_check_out_time = checkout_time_for_window(
                        checkout_window,
                        special_checkout_time
                    )
                    boarding_check_in = datetime.now()
                    boarding_check_out = datetime.combine(
                        boarding_check_out_date,
                        boarding_check_out_time
                    )

                    if boarding_check_out <= boarding_check_in:
                        st.warning(
                            "Boarding checkout must be after check-in."
                        )
                        can_add = False

                    permission_columns = st.columns(3)
                    permissions = [
                        (
                            "Kennel",
                            "Allowed"
                            if is_allowed(selected_row["kennel_allowed"])
                            else "Not allowed"
                        ),
                        (
                            "Suite",
                            "Allowed"
                            if is_allowed(selected_row["suite_allowed"])
                            else "Not allowed"
                        ),
                        (
                            "Floor",
                            "Allowed"
                            if is_allowed(selected_row["floor_allowed"])
                            else "Not allowed"
                        )
                    ]

                    for column, (label, value) in zip(
                        permission_columns,
                        permissions
                    ):
                        column.markdown(f"**{label}:** {value}")

                    requirement_details = [
                        f'Play group: {selected_row["play_group"]}',
                        f'Size class: {selected_row["size_class"]}',
                        (
                            "Fence jumper: Yes"
                            if is_allowed(selected_row["fence_jumpers"])
                            else "Fence jumper: No"
                        ),
                        (
                            "Fence fighter: Yes"
                            if is_allowed(selected_row["fence_fighter"])
                            else "Fence fighter: No"
                        )
                    ]
                    st.caption(" | ".join(requirement_details))

                    keep_together = (
                        sibling_rule is not None
                        and is_allowed(sibling_rule["keep_together"])
                    )
                    placement_mode = "Individual"
                    override_reason = ""

                    if sibling_rule is not None:
                        st.write(
                            "**Default placement:** "
                            + (
                                "Keep together"
                                if keep_together
                                else "Assign separately"
                            )
                        )

                    sibling_placement_needed = keep_together and (
                        selected_sibling_ids
                        or not present_siblings_df.empty
                    )

                    if sibling_placement_needed:
                        placement_mode = st.radio(
                            "Sibling Placement",
                            [
                                "Keep together",
                                "Separate siblings — override"
                            ],
                            horizontal=True,
                            key="boarding_sibling_placement"
                        )

                        if placement_mode == "Separate siblings — override":
                            override_reason = st.text_input(
                                "Reason for separating siblings",
                                placeholder="Required override reason...",
                                key="boarding_sibling_override_reason"
                            ).strip()

                    occupied_room_ids = set(
                        dogs_df["assigned_room_id"]
                        .dropna()
                        .astype(int)
                    )
                    blocked_room_ids = get_fence_fighter_blocked_room_ids(
                        dogs_df,
                        rooms_df
                    )

                    new_boarding_rows = [selected_row]

                    for sibling_id in selected_sibling_ids:
                        new_boarding_rows.append(
                            available_siblings_df[
                                available_siblings_df["dog_id"].astype(int)
                                == sibling_id
                            ].iloc[0]
                        )

                    selected_rooms = {}

                    if placement_mode == "Keep together":

                        boarding_siblings_present = present_siblings_df[
                            present_siblings_df["boarding_status"] == 1
                        ]
                        daycare_siblings_present = present_siblings_df[
                            present_siblings_df["boarding_status"] == 0
                        ]

                        if not daycare_siblings_present.empty:
                            st.warning(
                                "A keep-together sibling is currently checked "
                                "in as Daycare. Use the separation override or "
                                "correct that sibling's attendance first."
                            )
                            can_add = False

                        existing_shared_room_ids = set(
                            boarding_siblings_present["assigned_room_id"]
                            .dropna()
                            .astype(int)
                        )

                        shared_dogs = new_boarding_rows + [
                            sibling
                            for _, sibling in boarding_siblings_present.iterrows()
                        ]

                        if len(shared_dogs) > 1 and sibling_rule is not None:
                            eligible_rooms = get_shared_sibling_rooms(
                                shared_dogs,
                                sibling_rule,
                                rooms_df,
                                occupied_room_ids=occupied_room_ids,
                                blocked_room_ids=blocked_room_ids,
                                allowed_occupied_room_ids=(
                                    existing_shared_room_ids
                                )
                            )

                            if existing_shared_room_ids:
                                eligible_rooms = eligible_rooms[
                                    eligible_rooms["room_id"].astype(int).isin(
                                        existing_shared_room_ids
                                    )
                                ]
                        else:
                            eligible_rooms = get_eligible_boarding_rooms(
                                selected_row,
                                rooms_df,
                                occupied_room_ids=occupied_room_ids,
                                blocked_room_ids=blocked_room_ids
                            )

                        if eligible_rooms.empty:
                            st.error(
                                "No eligible available room was found for this "
                                "boarding placement."
                            )
                            can_add = False
                        else:
                            room_options = {
                                int(room["room_id"]): format_room_option(room)
                                for _, room in eligible_rooms.iterrows()
                            }
                            shared_room_id = st.selectbox(
                                "Boarding Room",
                                options=list(room_options),
                                format_func=room_options.get,
                                key="boarding_shared_room"
                            )

                            for dog in new_boarding_rows:
                                selected_rooms[int(dog["dog_id"])] = (
                                    shared_room_id
                                )

                    else:

                        if (
                            placement_mode
                            == "Separate siblings — override"
                            and not override_reason
                        ):
                            st.warning(
                                "Enter a reason to use the sibling separation "
                                "override."
                            )
                            can_add = False

                        reserved_during_form = set(occupied_room_ids)

                        for dog in new_boarding_rows:
                            dog_id = int(dog["dog_id"])
                            eligible_rooms = get_eligible_boarding_rooms(
                                dog,
                                rooms_df,
                                occupied_room_ids=reserved_during_form,
                                blocked_room_ids=blocked_room_ids
                            )

                            if eligible_rooms.empty:
                                st.error(
                                    f'No eligible available room was found for '
                                    f'{dog["dog_name"]}.'
                                )
                                can_add = False
                                continue

                            room_options = {
                                int(room["room_id"]): format_room_option(room)
                                for _, room in eligible_rooms.iterrows()
                            }
                            room_id = st.selectbox(
                                f'Boarding Room — {dog["dog_name"]}',
                                options=list(room_options),
                                format_func=room_options.get,
                                key=f"boarding_room_{dog_id}"
                            )
                            selected_rooms[dog_id] = room_id
                            reserved_during_form.add(room_id)

                    records_to_add = [
                        {
                            "dog_id": int(dog["dog_id"]),
                            "visit_type": "Boarding",
                            "assigned_room_id": selected_rooms.get(
                                int(dog["dog_id"])
                            ),
                            "check_in_datetime": boarding_check_in,
                            "planned_checkout_datetime": boarding_check_out
                        }
                        for dog in new_boarding_rows
                    ]

                    if any(
                        record["assigned_room_id"] is None
                        for record in records_to_add
                    ):
                        can_add = False

                if st.button(
                    (
                        "Add Selected Dogs to Today's Daycare"
                        if visit_type == "Daycare"
                        else "Check In Boarding Dog"
                    ),
                    key="add_attendance_submit",
                    use_container_width=True,
                    disabled=not can_add
                ):
                    add_attendance_records(records_to_add)

                    added_names = [
                        str(
                            available_dogs_df.loc[
                                available_dogs_df["dog_id"].astype(int)
                                == record["dog_id"],
                                "dog_name"
                            ].iloc[0]
                        )
                        for record in records_to_add
                    ]
                    st.success(
                        f'{", ".join(added_names)} added successfully!'
                    )
                    st.rerun()

        # -----------------------------------------
        # Edit Boarding Stay
        # -----------------------------------------

        with st.expander("Edit Boarding Stay"):

            active_boarders_df = dogs_df[
                (dogs_df["boarding_status"] == 1)
                & dogs_df["boarding_stay_id"].notna()
            ].copy()

            if active_boarders_df.empty:
                st.info("There are no active boarding stays to edit.")
            else:
                stay_options = {
                    int(row["boarding_stay_id"]): (
                        f'{row["dog_name"]} · Room '
                        f'{row["assigned_room_number"]}'
                    )
                    for _, row in active_boarders_df.sort_values(
                        by="dog_name",
                        key=lambda column: column.str.lower()
                    ).iterrows()
                }
                selected_stay_id = st.selectbox(
                    "Boarder",
                    options=list(stay_options),
                    format_func=stay_options.get,
                    key="edit_boarding_stay"
                )
                stay_dog = active_boarders_df[
                    active_boarders_df["boarding_stay_id"].astype(int)
                    == selected_stay_id
                ].iloc[0]
                boarding_siblings_df = active_boarders_df.iloc[0:0].copy()
                sibling_group_id = stay_dog["sibling_group_id"]

                if pd.notna(sibling_group_id):
                    boarding_siblings_df = active_boarders_df[
                        (
                            active_boarders_df["sibling_group_id"]
                            == sibling_group_id
                        )
                        & (
                            active_boarders_df["boarding_stay_id"].astype(int)
                            != selected_stay_id
                        )
                    ].copy()
                current_check_in = pd.Timestamp(
                    stay_dog["boarding_check_in"]
                ).to_pydatetime()
                current_check_out = pd.Timestamp(
                    stay_dog["boarding_check_out"]
                ).to_pydatetime()
                occupied_room_ids = set(
                    dogs_df[
                        dogs_df["attendance_id"].astype(int)
                        != int(stay_dog["attendance_id"])
                    ]["assigned_room_id"].dropna().astype(int)
                )
                blocked_room_ids = get_fence_fighter_blocked_room_ids(
                    dogs_df,
                    rooms_df
                )
                eligible_rooms = get_eligible_boarding_rooms(
                    stay_dog,
                    rooms_df,
                    occupied_room_ids=occupied_room_ids,
                    blocked_room_ids=blocked_room_ids
                )
                current_room_id = int(stay_dog["assigned_room_id"])

                if current_room_id not in set(
                    eligible_rooms["room_id"].astype(int)
                ):
                    eligible_rooms = pd.concat(
                        [
                            rooms_df[
                                rooms_df["room_id"].astype(int)
                                == current_room_id
                            ],
                            eligible_rooms
                        ],
                        ignore_index=True
                    )

                room_options = {
                    int(room["room_id"]): format_room_option(room)
                    for _, room in eligible_rooms.iterrows()
                }

                with st.form("edit_boarding_stay_form"):
                    sibling_stay_ids = []

                    for _, sibling in boarding_siblings_df.iterrows():
                        relationship = get_sibling_relationship(
                            sibling.get("gender", "")
                        )
                        apply_to_sibling = st.checkbox(
                            "**Apply these changes to "
                            f'{get_possessive_pronoun(stay_dog.get("gender", ""))} '
                            f'{relationship} {sibling["dog_name"]} too?**',
                            value=True,
                            key=(
                                "edit_boarding_sibling_"
                                f'{int(sibling["boarding_stay_id"])}'
                            )
                        )

                        if apply_to_sibling:
                            sibling_stay_ids.append(
                                int(sibling["boarding_stay_id"])
                            )

                    date_columns = st.columns(2)
                    edited_check_in_date = date_columns[0].date_input(
                        "Check-In Date",
                        value=current_check_in.date(),
                        format="MM/DD/YYYY"
                    )
                    edited_check_out_date = date_columns[1].date_input(
                        "Check-Out Date",
                        value=current_check_out.date(),
                        min_value=edited_check_in_date,
                        format="MM/DD/YYYY"
                    )
                    st.caption(
                        "The original check-in time is recorded "
                        "automatically and is not edited here."
                    )
                    current_checkout_time = current_check_out.time().replace(
                        second=0,
                        microsecond=0
                    )
                    checkout_windows = [
                        "AM", "PM", "TBD", "Special / Late Pickup"
                    ]
                    current_checkout_window = checkout_window_for_time(
                        current_checkout_time
                    )
                    edited_checkout_window = st.selectbox(
                        "Expected Pick-Up",
                        options=checkout_windows,
                        index=checkout_windows.index(current_checkout_window),
                        help=(
                            "AM uses noon, PM uses 7:00 PM, and TBD keeps "
                            "the stay active through the checkout date."
                        ),
                        key=(
                            "edit_boarding_checkout_window_"
                            f"{selected_stay_id}"
                        )
                    )
                    edited_special_checkout_time = None
                    if edited_checkout_window == "Special / Late Pickup":
                        available_checkout_times = checkout_time_options(
                            extra_time=current_checkout_time
                        )
                        edited_special_checkout_time = st.selectbox(
                            "Special Pick-Up Time",
                            options=available_checkout_times,
                            index=available_checkout_times.index(
                                current_checkout_time
                            ),
                            format_func=format_normal_time,
                            key=(
                                "edit_boarding_special_checkout_time_"
                                f"{selected_stay_id}"
                            )
                        )
                    edited_check_out_time = checkout_time_for_window(
                        edited_checkout_window,
                        edited_special_checkout_time
                    )
                    edited_room_id = st.selectbox(
                        "Boarding Room",
                        options=list(room_options),
                        index=list(room_options).index(current_room_id),
                        format_func=room_options.get
                    )
                    names_to_update = [
                        str(stay_dog["dog_name"]),
                        *[
                            str(sibling["dog_name"])
                            for _, sibling in boarding_siblings_df.iterrows()
                            if int(sibling["boarding_stay_id"])
                            in sibling_stay_ids
                        ]
                    ]
                    st.info(
                        "This will update: " + ", ".join(names_to_update)
                    )
                    confirm_stay_changes = st.checkbox(
                        "**Confirm these boarding stay changes**"
                    )
                    apply_stay_changes = st.form_submit_button(
                        "Apply Stay Changes",
                        type="primary",
                        use_container_width=True
                    )

                    if apply_stay_changes:
                        edited_check_in = datetime.combine(
                            edited_check_in_date,
                            current_check_in.time()
                        )
                        edited_check_out = datetime.combine(
                            edited_check_out_date,
                            edited_check_out_time
                        )

                        if not confirm_stay_changes:
                            st.warning(
                                "Confirm the boarding stay changes before "
                                "continuing."
                            )
                            return

                        try:
                            update_boarding_stays(
                                [selected_stay_id, *sibling_stay_ids],
                                edited_check_in,
                                edited_check_out,
                                edited_room_id
                            )
                        except (ValueError, TypeError) as error:
                            st.error(str(error))
                        except Exception:
                            st.error(
                                "The boarding stay could not be updated."
                            )
                        else:
                            st.success(
                                f'{", ".join(names_to_update)} updated '
                                "successfully!"
                            )
                            st.rerun()

        # -----------------------------------------
        # Switch Daycare Dog to Boarding
        # -----------------------------------------

        with st.expander("Switch Daycare Dog to Boarding"):

            active_daycare_df = dogs_df[
                dogs_df["boarding_status"] == 0
            ].copy()

            if active_daycare_df.empty:
                st.info("There are no Daycare dogs to switch to Boarding.")
            else:
                daycare_options = {
                    int(row["attendance_id"]): format_attendance_option(row)
                    for _, row in active_daycare_df.sort_values(
                        by="dog_name",
                        key=lambda column: column.str.lower()
                    ).iterrows()
                }
                switch_attendance_id = st.selectbox(
                    "Daycare Dog",
                    options=list(daycare_options),
                    format_func=daycare_options.get,
                    key="switch_daycare_boarding_dog"
                )
                switch_dog = active_daycare_df[
                    active_daycare_df["attendance_id"].astype(int)
                    == switch_attendance_id
                ].iloc[0]
                switch_rows = [switch_dog]
                switch_sibling_ids = []
                switch_sibling_rule = None
                switch_group_id = switch_dog["sibling_group_id"]

                if pd.notna(switch_group_id):
                    matching_rules = sibling_group_df[
                        sibling_group_df["sibling_group_id"].astype(int)
                        == int(switch_group_id)
                    ]
                    if not matching_rules.empty:
                        switch_sibling_rule = matching_rules.iloc[0]

                    daycare_siblings_df = active_daycare_df[
                        (active_daycare_df["sibling_group_id"] == switch_group_id)
                        & (
                            active_daycare_df["attendance_id"].astype(int)
                            != switch_attendance_id
                        )
                    ].copy()

                    if not daycare_siblings_df.empty:
                        st.markdown("#### Sibling Group")
                        for _, sibling in daycare_siblings_df.iterrows():
                            sibling_id = int(sibling["attendance_id"])
                            relationship = get_sibling_relationship(
                                sibling.get("gender", "")
                            )
                            include_sibling = st.checkbox(
                                "**Would you like to switch "
                                f'{get_possessive_pronoun(switch_dog.get("gender", ""))} '
                                f'{relationship} {sibling["dog_name"]} '
                                "to Boarding too?**",
                                key=f"switch_daycare_sibling_{sibling_id}"
                            )
                            if include_sibling:
                                switch_sibling_ids.append(sibling_id)
                                switch_rows.append(sibling)

                st.markdown("#### Boarding Requirements")
                switch_stay_columns = st.columns(2)
                switch_checkout_date = switch_stay_columns[0].date_input(
                    "Check-Out Date",
                    value=date.today() + timedelta(days=1),
                    min_value=date.today(),
                    format="MM/DD/YYYY",
                    key="switch_daycare_checkout_date"
                )
                switch_checkout_window = switch_stay_columns[1].selectbox(
                    "Expected Pick-Up",
                    ["AM", "PM", "TBD", "Special / Late Pickup"],
                    help=(
                        "AM uses noon, PM uses 7:00 PM, and TBD keeps "
                        "the stay active through the checkout date."
                    ),
                    key="switch_daycare_checkout_window"
                )
                switch_special_time = None
                if switch_checkout_window == "Special / Late Pickup":
                    switch_time_options = checkout_time_options()
                    switch_special_time = st.selectbox(
                        "Special Pick-Up Time",
                        options=switch_time_options,
                        index=switch_time_options.index(time(19, 0)),
                        format_func=format_normal_time,
                        key="switch_daycare_special_time"
                    )
                switch_checkout_datetime = datetime.combine(
                    switch_checkout_date,
                    checkout_time_for_window(
                        switch_checkout_window,
                        switch_special_time
                    )
                )
                switch_check_in = datetime.now()
                switch_can_submit = switch_checkout_datetime > switch_check_in

                if not switch_can_submit:
                    st.warning("Boarding checkout must be after check-in.")

                occupied_room_ids = set(
                    dogs_df["assigned_room_id"].dropna().astype(int)
                )
                blocked_room_ids = get_fence_fighter_blocked_room_ids(
                    dogs_df,
                    rooms_df
                )
                keep_switch_siblings_together = (
                    len(switch_rows) > 1
                    and switch_sibling_rule is not None
                    and is_allowed(switch_sibling_rule["keep_together"])
                )
                switch_placement = (
                    "Keep together" if keep_switch_siblings_together
                    else "Separate"
                )
                switch_override_reason = ""

                if keep_switch_siblings_together:
                    switch_placement = st.radio(
                        "Sibling Placement",
                        ["Keep together", "Separate — override"],
                        horizontal=True,
                        key="switch_daycare_sibling_placement"
                    )
                    if switch_placement == "Separate — override":
                        switch_override_reason = st.text_input(
                            "Reason for separating siblings",
                            placeholder="Required override reason...",
                            key="switch_daycare_override_reason"
                        ).strip()
                        if not switch_override_reason:
                            switch_can_submit = False

                switch_room_ids = {}

                if switch_placement == "Keep together":
                    eligible_switch_rooms = get_shared_sibling_rooms(
                        switch_rows,
                        switch_sibling_rule,
                        rooms_df,
                        occupied_room_ids=occupied_room_ids,
                        blocked_room_ids=blocked_room_ids
                    )
                    if eligible_switch_rooms.empty:
                        st.error(
                            "No eligible shared boarding room is available."
                        )
                        switch_can_submit = False
                    else:
                        room_options = {
                            int(room["room_id"]): format_room_option(room)
                            for _, room in eligible_switch_rooms.iterrows()
                        }
                        shared_room_id = st.selectbox(
                            "Boarding Room",
                            options=list(room_options),
                            format_func=room_options.get,
                            key="switch_daycare_shared_room"
                        )
                        for row in switch_rows:
                            switch_room_ids[int(row["attendance_id"])] = (
                                shared_room_id
                            )
                else:
                    reserved_room_ids = set(occupied_room_ids)
                    for row in switch_rows:
                        attendance_id = int(row["attendance_id"])
                        eligible_switch_rooms = get_eligible_boarding_rooms(
                            row,
                            rooms_df,
                            occupied_room_ids=reserved_room_ids,
                            blocked_room_ids=blocked_room_ids
                        )
                        if eligible_switch_rooms.empty:
                            st.error(
                                "No eligible available boarding room was "
                                f'found for {row["dog_name"]}.'
                            )
                            switch_can_submit = False
                            continue
                        room_options = {
                            int(room["room_id"]): format_room_option(room)
                            for _, room in eligible_switch_rooms.iterrows()
                        }
                        selected_room_id = st.selectbox(
                            f'Boarding Room — {row["dog_name"]}',
                            options=list(room_options),
                            format_func=room_options.get,
                            key=f"switch_daycare_room_{attendance_id}"
                        )
                        switch_room_ids[attendance_id] = selected_room_id
                        reserved_room_ids.add(selected_room_id)

                switch_names = [str(row["dog_name"]) for row in switch_rows]
                st.info("Switching to Boarding: " + ", ".join(switch_names))
                confirm_switch = st.checkbox(
                    "**Confirm switch to Boarding**",
                    key="confirm_daycare_to_boarding"
                )

                if st.button(
                    "Switch to Boarding",
                    type="primary",
                    use_container_width=True,
                    disabled=not switch_can_submit,
                    key="switch_daycare_to_boarding_submit"
                ):
                    if not confirm_switch:
                        st.warning("Confirm the switch before continuing.")
                    else:
                        switch_records = [
                            {
                                "attendance_id": int(row["attendance_id"]),
                                "assigned_room_id": switch_room_ids.get(
                                    int(row["attendance_id"])
                                ),
                                "check_in_datetime": switch_check_in,
                                "planned_checkout_datetime": (
                                    switch_checkout_datetime
                                )
                            }
                            for row in switch_rows
                        ]
                        try:
                            switch_daycare_to_boarding(switch_records)
                        except (ValueError, TypeError) as error:
                            st.error(str(error))
                        except Exception:
                            st.error(
                                "The Daycare attendance could not be "
                                "switched to Boarding."
                            )
                        else:
                            st.session_state["attendance_notice"] = (
                                switched_attendance_message(
                                    switch_names,
                                    "Boarding"
                                )
                            )
                            st.rerun()

        # -----------------------------------------
        # Remove Dog
        # -----------------------------------------

        with st.expander("Remove Dog"):

            if dogs_df.empty:

                st.info("There are no dogs in today's attendance.")

            else:

                remove_search = st.text_input(
                    "Search Dog to Remove",
                    placeholder="Search by name or nickname...",
                    key="remove_dog_search"
                )

                removal_dogs_df = dogs_df.copy()

                if remove_search:

                    name_matches = removal_dogs_df[
                        "dog_name"
                    ].str.contains(
                        remove_search,
                        case=False,
                        na=False
                    )

                    nickname_matches = removal_dogs_df[
                        "dog_nickname"
                    ].fillna("").astype(str).str.contains(
                        remove_search,
                        case=False,
                        na=False
                    )

                    removal_dogs_df = removal_dogs_df[
                        name_matches | nickname_matches
                    ]

                attendance_options = {
                    int(row["attendance_id"]): format_attendance_option(row)
                    for _, row in removal_dogs_df.sort_values(
                        by="dog_name",
                        key=lambda column: column.str.lower()
                    ).iterrows()
                }

                if not attendance_options:

                    st.info("No dogs matched that search.")

                else:

                    selected_attendance_id = st.selectbox(
                        "Dog",
                        options=list(attendance_options),
                        format_func=attendance_options.get,
                        key="remove_attendance_dog"
                    )

                    selected_attendance_row = dogs_df[
                        dogs_df["attendance_id"].astype(int)
                        == selected_attendance_id
                    ].iloc[0]
                    selected_is_boarding = (
                        int(selected_attendance_row["boarding_status"]) == 1
                    )

                    present_siblings_df = dogs_df.iloc[0:0].copy()
                    sibling_group_id = selected_attendance_row[
                        "sibling_group_id"
                    ]

                    if pd.notna(sibling_group_id):
                        present_siblings_df = dogs_df[
                            (dogs_df["sibling_group_id"] == sibling_group_id)
                            & (
                                dogs_df["attendance_id"].astype(int)
                                != selected_attendance_id
                            )
                        ].copy()

                        if selected_is_boarding:
                            present_siblings_df = present_siblings_df[
                                present_siblings_df["boarding_status"] == 1
                            ].copy()

                    possessive_pronoun = get_possessive_pronoun(
                        selected_attendance_row.get("gender", "")
                    )

                    with st.form("remove_dog_form"):

                        sibling_attendance_ids = []

                        for _, sibling in present_siblings_df.iterrows():
                            sibling_name = str(sibling["dog_name"])
                            relationship = get_sibling_relationship(
                                sibling.get("gender", "")
                            )

                            remove_sibling = st.checkbox(
                                (
                                    "**Would you like to "
                                + (
                                    "apply this boarding action to "
                                    if selected_is_boarding
                                    else "remove "
                                )
                                    + f"{possessive_pronoun} {relationship} "
                                    + f"{sibling_name} too?**"
                                ),
                                value=selected_is_boarding,
                                key=(
                                    "remove_sibling_"
                                    f'{int(sibling["attendance_id"])}'
                                )
                            )

                            if remove_sibling:
                                sibling_attendance_ids.append(
                                    int(sibling["attendance_id"])
                                )

                        boarding_action = None

                        if selected_is_boarding:
                            st.markdown("#### End Boarding Stay")
                            boarding_action = st.radio(
                                "What should happen next?",
                                [
                                    "Check Out Boarder",
                                    "Switch to Daycare"
                                ],
                                help=(
                                    "Switch to Daycare releases the boarding "
                                    "room but keeps the dog present today."
                                )
                            )
                            boarding_action_names = [
                                str(selected_attendance_row["dog_name"]),
                                *[
                                    str(sibling["dog_name"])
                                    for _, sibling in present_siblings_df.iterrows()
                                    if int(sibling["attendance_id"])
                                    in sibling_attendance_ids
                                ]
                            ]
                            st.info(
                                f"{boarding_action} will apply to: "
                                + ", ".join(boarding_action_names)
                            )

                        confirm_removal = st.checkbox(
                            (
                                "**Confirm this boarding action**"
                                if selected_is_boarding
                                else "Confirm removal from today's attendance"
                            )
                        )

                        remove_submitted = st.form_submit_button(
                            (
                                "Update Boarding Attendance"
                                if selected_is_boarding
                                else "Remove Dog"
                            ),
                            use_container_width=True
                        )

                        if remove_submitted:

                            if not confirm_removal:

                                st.warning(
                                    "Confirm the removal before continuing."
                                )

                            else:

                                if selected_is_boarding:
                                    attendance_ids_to_update = [
                                        selected_attendance_id,
                                        *sibling_attendance_ids
                                    ]
                                    try:
                                        end_boarding_stays(
                                            attendance_ids_to_update,
                                            switch_to_daycare=(
                                                boarding_action
                                                == "Switch to Daycare"
                                            )
                                        )
                                    except (ValueError, TypeError) as error:
                                        st.error(str(error))
                                    except Exception:
                                        st.error(
                                            "The boarding attendance could "
                                            "not be updated."
                                        )
                                    else:
                                        if (
                                            boarding_action
                                            == "Switch to Daycare"
                                        ):
                                            st.session_state[
                                                "attendance_notice"
                                            ] = switched_attendance_message(
                                                boarding_action_names,
                                                "Daycare"
                                            )
                                        else:
                                            st.session_state[
                                                "attendance_notice"
                                            ] = (
                                                f'{", ".join(boarding_action_names)} '
                                                "checked out successfully."
                                            )
                                        st.rerun()

                                else:

                                    attendance_ids_to_remove = [
                                        selected_attendance_id,
                                        *sibling_attendance_ids
                                    ]

                                    removed_count = remove_attendance_records(
                                        attendance_ids_to_remove
                                    )

                                    if removed_count == len(
                                        attendance_ids_to_remove
                                    ):

                                        removed_names = [
                                            str(row["dog_name"])
                                            for _, row in dogs_df[
                                                dogs_df["attendance_id"].astype(int)
                                                .isin(attendance_ids_to_remove)
                                            ].iterrows()
                                        ]

                                        st.success(
                                            f'{", ".join(removed_names)} removed '
                                            "successfully!"
                                        )
                                        st.rerun()

                                    else:

                                        st.warning(
                                            "That attendance record was not found. "
                                            "Refresh the page and try again."
                                        )

        # -----------------------------------------
        # Refresh
        # -----------------------------------------

        if st.button(
            "Refresh",
            key="attendance_refresh",
            use_container_width=True
        ):
            st.rerun()
