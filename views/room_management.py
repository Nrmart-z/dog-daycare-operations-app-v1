import pandas as pd
import streamlit as st

from database import load_rooms, update_room_availability


ROOM_SECTIONS = (
    ("Petite Suites", tuple(range(1, 11))),
    ("Condo Suites", tuple(range(11, 26))),
    ("Kennels", tuple(range(42, 54))),
    ("Crate Room", (59, 60)),
    ("Floors", ("SMFL", "MDFL", "LGFL")),
    ("Front Kennel", tuple(range(54, 59))),
    ("Back Hall", (27, 28, 29, 34, 36, 38))
)


def normalize_room_number(value):

    value = str(value).strip()

    try:
        return int(value)
    except ValueError:
        return value.upper()


def get_section_rooms(rooms_df, room_identifiers):

    identifiers = set(room_identifiers)
    section_df = rooms_df.copy()
    section_df["normalized_room"] = section_df["room_number"].map(
        normalize_room_number
    )
    section_df = section_df[
        section_df["normalized_room"].isin(identifiers)
    ].copy()

    sort_order = {
        identifier: index
        for index, identifier in enumerate(room_identifiers)
    }
    section_df["section_sort"] = section_df["normalized_room"].map(
        sort_order
    )

    return section_df.sort_values("section_sort")


def room_display_name(room):

    if str(room["room_type"]).strip().lower() == "floor":
        return str(room["room_name"])

    return str(room["room_number"])


def save_room_availability(
    room_id,
    toggle_key,
    previous_value,
    room_label,
    section_name
):

    new_value = bool(st.session_state[toggle_key])
    st.session_state["room_management_open_section"] = section_name

    try:
        update_room_availability({int(room_id): new_value})
    except Exception:
        st.session_state[toggle_key] = previous_value
        st.session_state["room_management_feedback"] = (
            "error",
            f"Room {room_label} could not be updated. Please try again."
        )
    else:
        availability = "available" if new_value else "closed"
        st.session_state["room_management_feedback"] = (
            "success",
            f"Room {room_label} is now {availability}."
        )


def save_section_availability(room_ids, is_available, section_name):

    room_ids = [int(room_id) for room_id in room_ids]
    st.session_state["room_management_open_section"] = section_name

    try:
        update_room_availability(
            {room_id: bool(is_available) for room_id in room_ids}
        )
    except Exception:
        st.session_state["room_management_feedback"] = (
            "error",
            f"{section_name} could not be updated. Please try again."
        )
    else:
        availability = "available" if is_available else "closed"
        st.session_state["room_management_feedback"] = (
            "success",
            f"All {len(room_ids)} rooms in {section_name} are now "
            f"{availability}."
        )


@st.fragment
def render_room_controls():

    rooms_df = load_rooms()

    if rooms_df.empty:
        st.info("No rooms were found.")
        return

    usable_sections = []

    for section_name, identifiers in ROOM_SECTIONS:
        section_df = get_section_rooms(rooms_df, identifiers)

        if not section_df.empty:
            usable_sections.append((section_name, section_df))

    usable_rooms_df = pd.concat(
        [section_df for _, section_df in usable_sections],
        ignore_index=True
    )
    open_count = int(
        (usable_rooms_df["status"].fillna(0).astype(int) == 1).sum()
    )
    closed_count = len(usable_rooms_df) - open_count

    feedback = st.session_state.pop("room_management_feedback", None)

    if feedback:
        feedback_type, message = feedback

        if feedback_type == "success":
            st.success(message)
        else:
            st.error(message)

    st.write("")
    summary_columns = st.columns(3)
    summary_columns[0].metric("Usable Rooms", len(usable_rooms_df))
    summary_columns[1].metric("Available", open_count)
    summary_columns[2].metric("Closed", closed_count)

    st.caption(
        "Green/On = Available · Red/Off = Closed. "
        "Each switch saves immediately."
    )

    open_section = st.session_state.get("room_management_open_section")

    for section_name, section_df in usable_sections:
        section_open = int(
            (section_df["status"].fillna(0).astype(int) == 1).sum()
        )
        section_container = st.expander(
            section_name,
            expanded=section_name == open_section
        )

        with section_container:
            st.caption(
                f"{section_open} of {len(section_df)} rooms "
                "currently available"
            )
            table_space = st.columns([1, 4, 1])

            with table_space[1]:
                section_room_ids = section_df["room_id"].astype(int).tolist()
                bulk_columns = st.columns(2)
                bulk_columns[0].button(
                    "Open All",
                    type="primary",
                    use_container_width=True,
                    disabled=section_open == len(section_df),
                    key=f"open_all_{section_name}",
                    on_click=save_section_availability,
                    args=(section_room_ids, True, section_name)
                )
                bulk_columns[1].button(
                    "Close All",
                    use_container_width=True,
                    disabled=section_open == 0,
                    key=f"close_all_{section_name}",
                    on_click=save_section_availability,
                    args=(section_room_ids, False, section_name)
                )
                st.divider()
                header_columns = st.columns([2, 1])
                header_columns[0].markdown("**Room**")
                header_columns[1].markdown("**Available**")

                for _, room in section_df.iterrows():
                    room_id = int(room["room_id"])
                    toggle_key = f"room_available_{room_id}"
                    current_status = int(room["status"] or 0) == 1
                    row_status = "open" if current_status else "closed"

                    st.session_state[toggle_key] = current_status

                    room_row = st.container(
                        key=f"room_row_{row_status}_{room_id}"
                    )

                    with room_row:
                        row_columns = st.columns([2, 1])
                        room_label = room_display_name(room)
                        row_columns[0].write(room_label)
                        availability_text = (
                            "🟢 Yes" if current_status else "🔴 No"
                        )
                        row_columns[1].toggle(
                            availability_text,
                            key=toggle_key,
                            on_change=save_room_availability,
                            args=(
                                room_id,
                                toggle_key,
                                current_status,
                                room_label,
                                section_name
                            )
                        )


def show_room_management():

    st.title("Room Management")
    st.caption("Open or close usable daycare rooms")

    render_room_controls()
