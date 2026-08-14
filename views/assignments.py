import pandas as pd
import streamlit as st

from assignment_service import generate_assignment_draft
from room_capacity import remaining_space_tables
from database import (
    load_dogs,
    load_rooms,
    load_sibling_group,
    load_todays_assignments,
    save_daily_assignments
)


SECTION_ORDER = (
    "Petite Suites",
    "Condo Suites",
    "Kennels",
    "Front Kennel",
    "Crate Room",
    "Nap Crates",
    "Floors",
    "Back Hall"
)


def native_value(value):

    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def room_section(room):

    room_type = str(room.get("room_type") or "").strip().lower()
    room_number = str(room.get("room_number") or "").strip()

    try:
        numeric_room = int(room_number)
    except ValueError:
        numeric_room = None

    if room_type == "crate":
        return "Nap Crates"
    if room_type == "floor":
        return "Floors"
    if numeric_room is not None:
        if 1 <= numeric_room <= 10:
            return "Petite Suites"
        if 11 <= numeric_room <= 25:
            return "Condo Suites"
        if numeric_room in {27, 28, 29, 34, 36, 38}:
            return "Back Hall"
        if 42 <= numeric_room <= 53:
            return "Kennels"
        if 54 <= numeric_room <= 58:
            return "Front Kennel"
        if numeric_room in {59, 60}:
            return "Crate Room"
    return None


def room_label(room):

    if str(room.get("room_type") or "").strip().lower() == "floor":
        return str(room.get("room_name") or room.get("room_number"))
    return str(room.get("room_number") or room.get("room_id"))


def room_sort_key(room):

    label = str(room.get("room_number") or "")

    try:
        return (0, int(label))
    except ValueError:
        prefix_order = {
            "SMFL": 1,
            "MDFL": 2,
            "LGFL": 3,
            "XS": 10,
            "SM": 20,
            "M": 30,
            "L": 40,
            "XL": 50,
            "XXL": 60
        }
        prefix = next(
            (
                key
                for key in ("XXL", "XL", "XS", "SM", "M", "L")
                if label.upper().startswith(key)
            ),
            label.upper()
        )
        number = "".join(character for character in label if character.isdigit())
        return (
            1,
            prefix_order.get(prefix, 999),
            int(number) if number else 0,
            label
        )


def shared_sibling_room_ids(group_records, sibling_rule, rooms_df):

    shared_priorities = {}
    for room_type, allowed_field, priority_field in (
        ("Suite", "shared_suite_allowed", "shared_suite_priority"),
        ("Floor", "shared_floor_allowed", "shared_floor_priority"),
        ("Kennel", "shared_kennel_allowed", "shared_kennel_priority")
    ):
        if (
            int(sibling_rule.get(allowed_field) or 0) == 1
            and int(sibling_rule.get(priority_field) or 0) > 0
        ):
            shared_priorities[room_type] = int(
                sibling_rule[priority_field]
            )

    size_score = {"Small": 1, "Medium": 2, "Big": 3}
    total_score = sum(
        size_score.get(str(record.get("size_class") or "").strip(), 3)
        for record in group_records
    )

    if len(group_records) >= 3:
        allowed_capacities = {"Large"}
    elif total_score == 2:
        allowed_capacities = {"Small", "Medium"}
    elif total_score in {3, 4, 5}:
        allowed_capacities = {"Medium", "Medium/Large", "Large"}
    else:
        allowed_capacities = {"Medium/Large", "Large"}

    eligible = rooms_df[
        rooms_df["shared_room_type"].isin(shared_priorities)
        & rooms_df["sibling_capacity"].isin(allowed_capacities)
    ].copy()

    return set(eligible["room_id"].astype(int))


def assignment_row_style(row):

    status = str(row["Status"])

    if status == "Closed":
        background = "background-color: rgba(237, 50, 35, 0.20)"
    elif status == "Occupied":
        background = "background-color: rgba(255, 193, 7, 0.20)"
    else:
        background = "background-color: rgba(46, 125, 50, 0.12)"

    return [background] * len(row)


def finalized_records(assignments_df):

    records = []

    for _, row in assignments_df.iterrows():
        records.append(
            {
                "dog_id": int(row["dog_id"]),
                "dog_name": str(row["dog_name"]),
                "room_id": int(row["room_id"]),
                "room_number": str(row["room_number"]),
                "room_name": str(row["room_name"] or ""),
                "room_type": str(row["room_type"] or ""),
                "play_group": str(row["play_group"] or ""),
                "size_class": str(row["size_class"] or ""),
                "sibling_group_id": native_value(row["sibling_group_id"]),
                "visit_type": str(row["visit_type"] or "Daycare"),
                "assignment_type": str(row["assignment_type"]),
                "override_reason": native_value(row["override_reason"]),
                "locked": str(row["visit_type"]) == "Boarding"
            }
        )

    return records


def unassigned_attendance_record(dog, reason):

    return {
        "dog_id": int(dog["dog_id"]),
        "dog_name": str(dog["dog_name"]),
        "play_group": str(dog.get("play_group") or ""),
        "size_class": str(dog.get("size_class") or ""),
        "sibling_group_id": native_value(dog.get("sibling_group_id")),
        "visit_type": (
            "Boarding" if int(dog.get("boarding_status") or 0) == 1
            else "Daycare"
        ),
        "reason": reason
    }


def reconcile_finalized_assignments(assignments_df, dogs_df, rooms_df):

    saved = finalized_records(assignments_df)
    present_dogs = {
        int(row["dog_id"]): row
        for _, row in dogs_df.iterrows()
    }
    room_lookup = {
        int(row["room_id"]): row
        for _, row in rooms_df.iterrows()
    }
    reconciled = []
    unassigned = []
    removed_names = []
    new_names = []
    changed_names = []
    processed_dog_ids = set()

    for assignment in saved:
        dog_id = int(assignment["dog_id"])
        dog = present_dogs.get(dog_id)

        if dog is None:
            removed_names.append(assignment["dog_name"])
            continue

        processed_dog_ids.add(dog_id)
        is_boarding = int(dog.get("boarding_status") or 0) == 1
        was_boarding = assignment.get("visit_type") == "Boarding"

        if is_boarding:
            assigned_room_id = native_value(dog.get("assigned_room_id"))

            if assigned_room_id is None:
                unassigned.append(
                    unassigned_attendance_record(
                        dog,
                        "Boarding dog needs a boarding room"
                    )
                )
                changed_names.append(str(dog["dog_name"]))
                continue

            assigned_room_id = int(assigned_room_id)
            room = room_lookup[assigned_room_id]

            if (
                not was_boarding
                or int(assignment["room_id"]) != assigned_room_id
            ):
                changed_names.append(str(dog["dog_name"]))

            assignment.update(
                {
                    "room_id": assigned_room_id,
                    "room_number": str(room["room_number"]),
                    "room_name": str(room["room_name"] or ""),
                    "room_type": str(room["room_type"] or ""),
                    "visit_type": "Boarding",
                    "assignment_type": "Boarding Reservation",
                    "locked": True
                }
            )
            reconciled.append(assignment)
        elif was_boarding:
            unassigned.append(
                unassigned_attendance_record(
                    dog,
                    "Visit changed from Boarding to Daycare"
                )
            )
            changed_names.append(str(dog["dog_name"]))
        else:
            assignment["visit_type"] = "Daycare"
            assignment["locked"] = False
            reconciled.append(assignment)

    for dog_id, dog in present_dogs.items():
        if dog_id in processed_dog_ids:
            continue

        new_names.append(str(dog["dog_name"]))
        is_boarding = int(dog.get("boarding_status") or 0) == 1
        assigned_room_id = native_value(dog.get("assigned_room_id"))

        if is_boarding and assigned_room_id is not None:
            room = room_lookup[int(assigned_room_id)]
            reconciled.append(
                {
                    "dog_id": dog_id,
                    "dog_name": str(dog["dog_name"]),
                    "room_id": int(assigned_room_id),
                    "room_number": str(room["room_number"]),
                    "room_name": str(room["room_name"] or ""),
                    "room_type": str(room["room_type"] or ""),
                    "play_group": str(dog.get("play_group") or ""),
                    "size_class": str(dog.get("size_class") or ""),
                    "sibling_group_id": native_value(
                        dog.get("sibling_group_id")
                    ),
                    "visit_type": "Boarding",
                    "assignment_type": "Boarding Reservation",
                    "override_reason": None,
                    "locked": True
                }
            )
        else:
            unassigned.append(
                unassigned_attendance_record(
                    dog,
                    "New arrival since assignments were finalized"
                )
            )

    return {
        "assignments": reconciled,
        "unassigned": unassigned,
        "new_names": new_names,
        "removed_names": removed_names,
        "changed_names": changed_names
    }


def build_room_board(rooms_df, assignments):

    assignments_by_room = {}

    for assignment in assignments:
        assignments_by_room.setdefault(
            int(assignment["room_id"]),
            []
        ).append(assignment)

    sections = {section: [] for section in SECTION_ORDER}

    for _, room in rooms_df.iterrows():
        room_record = room.to_dict()
        section = room_section(room_record)

        if section is None:
            continue

        occupants = assignments_by_room.get(int(room["room_id"]), [])
        status = (
            "Occupied"
            if occupants
            else "Available"
            if int(room["status"] or 0) == 1
            else "Closed"
        )
        sections[section].append(
            {
                "sort": room_sort_key(room_record),
                "Room": room_label(room_record),
                "Assigned Dog(s)": ", ".join(
                    occupant["dog_name"] for occupant in occupants
                ),
                "Visit": ", ".join(
                    dict.fromkeys(
                        occupant["visit_type"] for occupant in occupants
                    )
                ),
                "Play Group": ", ".join(
                    dict.fromkeys(
                        occupant["play_group"] for occupant in occupants
                    )
                ),
                "Status": status
            }
        )

    return sections


def display_room_board(rooms_df, assignments):

    sections = build_room_board(rooms_df, assignments)

    st.subheader("Room Assignment Board", anchor=False)
    st.caption(
        "Green = available · Yellow = occupied · Red = closed"
    )

    for section_name in SECTION_ORDER:
        rows = sections[section_name]

        if not rows:
            continue

        occupied_count = sum(row["Status"] == "Occupied" for row in rows)

        with st.expander(
            f"{section_name} — {occupied_count} occupied",
            expanded=False
        ):
            section_df = pd.DataFrame(
                sorted(rows, key=lambda row: row["sort"])
            ).drop(columns="sort")
            st.dataframe(
                section_df.style.apply(assignment_row_style, axis=1),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 + (35 * len(section_df)))
            )


def show_assignments():

    dogs_df = load_dogs()
    rooms_df = load_rooms()
    sibling_groups_df = load_sibling_group()
    saved_assignments_df = load_todays_assignments()

    st.title("Nap-Time Assignments")
    st.caption("Generate, review, adjust, and finalize today's room plan")

    notice = st.session_state.pop("assignment_notice", None)

    if notice:
        st.success(notice)

    draft = st.session_state.get("assignment_draft")
    unassigned = st.session_state.get("assignment_unassigned", [])

    if draft is not None:
        page_status = "Draft"
        displayed_assignments = draft
    elif not saved_assignments_df.empty:
        page_status = "Finalized"
        displayed_assignments = finalized_records(saved_assignments_df)
    else:
        page_status = "TBD"
        displayed_assignments = []

    boarding_count = int((dogs_df["boarding_status"] == 1).sum())
    daycare_count = len(dogs_df) - boarding_count
    daycare_assigned = sum(
        assignment["visit_type"] == "Daycare"
        for assignment in displayed_assignments
    )

    st.write("")
    summary_columns = st.columns(6)
    summary_columns[0].metric("Dogs Present", len(dogs_df))
    summary_columns[1].metric("Boarding", boarding_count)
    summary_columns[2].metric("Daycare", daycare_count)
    summary_columns[3].metric("Daycare Assigned", daycare_assigned)
    summary_columns[4].metric("Unassigned", len(unassigned))
    summary_columns[5].metric("Status", page_status)

    action_columns = st.columns(2)

    if page_status == "Finalized":
        reconciliation = reconcile_finalized_assignments(
            saved_assignments_df,
            dogs_df,
            rooms_df
        )
        attendance_changes = (
            reconciliation["new_names"]
            or reconciliation["removed_names"]
            or reconciliation["changed_names"]
        )

        if attendance_changes:
            st.warning(
                "Attendance has changed since finalization. Edit today's "
                "assignments to review late arrivals, cancellations, or "
                "visit changes."
            )

            if reconciliation["new_names"]:
                st.info(
                    "**New since finalization:** "
                    + ", ".join(reconciliation["new_names"])
                )

            if reconciliation["removed_names"]:
                st.info(
                    "**No longer attending:** "
                    + ", ".join(reconciliation["removed_names"])
                )

            if reconciliation["changed_names"]:
                st.info(
                    "**Visit or boarding room changed:** "
                    + ", ".join(reconciliation["changed_names"])
                )

        if action_columns[0].button(
            "Edit Finalized Assignments",
            use_container_width=True,
            key="reopen_assignments"
        ):
            with st.spinner("Preparing room suggestions..."):
                generated_suggestions = generate_assignment_draft()
            st.session_state["assignment_draft"] = reconciliation[
                "assignments"
            ]
            st.session_state["assignment_unassigned"] = reconciliation[
                "unassigned"
            ]
            st.session_state["assignment_editing_finalized"] = True
            st.session_state["assignment_room_suggestions"] = (
                generated_suggestions["suggested_room_ids_by_dog"]
            )
            st.session_state["assignment_notice"] = (
                "Finalized assignments reopened and synchronized with "
                "current attendance."
            )
            st.rerun()
    else:
        generate_label = (
            "Regenerate Automatic Assignments"
            if page_status == "Draft"
            else "Generate Automatic Assignments"
        )

        if action_columns[0].button(
            generate_label,
            type="primary",
            use_container_width=True,
            key="generate_assignments"
        ):
            try:
                with st.spinner("Running the assignment engine..."):
                    generated = generate_assignment_draft()
            except Exception:
                st.error(
                    "Assignments could not be generated. Please verify "
                    "today's attendance and room availability."
                )
            else:
                st.session_state["assignment_draft"] = generated[
                    "assignments"
                ]
                st.session_state["assignment_unassigned"] = generated[
                    "unassigned"
                ]
                st.session_state["assignment_room_suggestions"] = generated[
                    "suggested_room_ids_by_dog"
                ]
                st.session_state["assignment_editing_finalized"] = False
                st.session_state["assignment_notice"] = (
                    "Automatic assignments generated as a draft."
                )
                st.rerun()

    if displayed_assignments:
        display_room_board(rooms_df, displayed_assignments)
    elif page_status == "TBD":
        st.info(
            "Generate automatic assignments to create today's draft room plan."
        )

    if draft is not None:
        st.write("")
        st.markdown(
            '<span class="prominent-action-marker '
            'manual-assignment-marker"></span>',
            unsafe_allow_html=True
        )
        manual = st.expander("Manual Move or Override", expanded=True)

        with manual:
            movable_assignments = [
                assignment
                for assignment in draft
                if not assignment.get("locked", False)
            ]
            dog_options = {
                f'assigned:{assignment["dog_id"]}': (
                    f'{assignment["dog_name"]} — Current room '
                    f'{assignment["room_number"]}'
                )
                for assignment in movable_assignments
            }
            dog_options.update(
                {
                    f'unassigned:{dog["dog_id"]}': (
                        f'{dog["dog_name"]} — Unassigned'
                    )
                    for dog in unassigned
                }
            )

            if not dog_options:
                st.info("There are no daycare dogs available to move.")
            else:
                selected_dog_key = st.selectbox(
                    "Dog",
                    options=list(dog_options),
                    format_func=dog_options.get,
                    key="manual_assignment_dog"
                )
                selected_source, selected_dog_id_text = (
                    selected_dog_key.split(":")
                )
                selected_dog_id = int(selected_dog_id_text)
                selected_dog_record = next(
                    item
                    for item in [*draft, *unassigned]
                    if int(item["dog_id"]) == selected_dog_id
                )
                sibling_move_mode = "Move individually"
                sibling_override_reason = ""
                moving_records = [selected_dog_record]
                sibling_group_id = selected_dog_record.get(
                    "sibling_group_id"
                )
                sibling_rule = None

                if sibling_group_id is not None:
                    matching_rules = sibling_groups_df[
                        sibling_groups_df["sibling_group_id"].astype(int)
                        == int(sibling_group_id)
                    ]
                    if not matching_rules.empty:
                        sibling_rule = matching_rules.iloc[0]
                        group_records = [
                            record
                            for record in [*draft, *unassigned]
                            if record.get("sibling_group_id") is not None
                            and int(record["sibling_group_id"])
                            == int(sibling_group_id)
                            and not record.get("locked", False)
                        ]
                        if (
                            int(sibling_rule.get("keep_together") or 0) == 1
                            and len(group_records) > 1
                        ):
                            st.markdown("#### Sibling Move")
                            st.info(
                                "Keep-together group: "
                                + ", ".join(
                                    record["dog_name"]
                                    for record in group_records
                                )
                            )
                            sibling_move_mode = st.radio(
                                "How should this sibling group be moved?",
                                ["Move Together", "Separate — Override"],
                                horizontal=True,
                                key="manual_sibling_move_mode"
                            )
                            if sibling_move_mode == "Move Together":
                                moving_records = group_records
                            else:
                                sibling_override_reason = st.text_input(
                                    "Sibling Separation Reason *",
                                    max_chars=200,
                                    placeholder=(
                                        "Explain why the siblings are being "
                                        "separated"
                                    ),
                                    key="manual_sibling_separation_reason"
                                )
                open_rooms_df = rooms_df[
                    rooms_df["status"].fillna(0).astype(int) == 1
                ].copy()
                occupied_by_room = {}

                for assignment in draft:
                    occupied_by_room.setdefault(
                        int(assignment["room_id"]),
                        []
                    ).append(assignment)

                room_options = {}

                for _, room in open_rooms_df.iterrows():
                    room_record = room.to_dict()

                    if room_section(room_record) is None:
                        continue

                    room_id = int(room["room_id"])
                    occupants = occupied_by_room.get(room_id, [])
                    occupant_text = (
                        " · Occupied by "
                        + ", ".join(item["dog_name"] for item in occupants)
                        if occupants
                        else " · Available"
                    )
                    room_options[room_id] = (
                        f'{room_label(room_record)} · '
                        f'{room["room_type"]}{occupant_text}'
                    )

                suggestion_lookup = st.session_state.get(
                    "assignment_room_suggestions", {}
                )

                if not suggestion_lookup:
                    try:
                        with st.spinner("Loading suggested rooms..."):
                            generated_suggestions = (
                                generate_assignment_draft()
                            )
                    except Exception:
                        st.warning(
                            "Suggested rooms could not be refreshed. Other "
                            "open rooms are still available below."
                        )
                    else:
                        suggestion_lookup = generated_suggestions[
                            "suggested_room_ids_by_dog"
                        ]
                        st.session_state[
                            "assignment_room_suggestions"
                        ] = suggestion_lookup

                suggested_room_ids = [
                    int(room_id)
                    for room_id in suggestion_lookup.get(
                        selected_dog_id,
                        suggestion_lookup.get(str(selected_dog_id), [])
                    )
                    if int(room_id) in room_options
                ]
                if sibling_move_mode == "Move Together" and sibling_rule is not None:
                    shared_room_ids = shared_sibling_room_ids(
                        moving_records,
                        sibling_rule,
                        rooms_df
                    )
                    group_suggestion_sets = []
                    for record in moving_records:
                        record_id = int(record["dog_id"])
                        group_suggestion_sets.append({
                            int(room_id)
                            for room_id in suggestion_lookup.get(
                                record_id,
                                suggestion_lookup.get(str(record_id), [])
                            )
                        })
                    shared_suggested_ids = (
                        set.intersection(*group_suggestion_sets)
                        if group_suggestion_sets
                        else set()
                    )
                    suggested_room_ids = [
                        room_id
                        for room_id in suggested_room_ids
                        if room_id in shared_room_ids
                        and room_id in shared_suggested_ids
                    ]
                    room_options = {
                        room_id: label
                        for room_id, label in room_options.items()
                        if room_id in shared_room_ids
                    }
                other_room_ids = sorted(
                    list(room_options),
                    key=lambda room_id: room_sort_key(
                        rooms_df[
                            rooms_df["room_id"].astype(int) == room_id
                        ].iloc[0].to_dict()
                    )
                )

                st.markdown("#### Suggested Rooms")

                if suggested_room_ids:
                    suggested_room_id = st.selectbox(
                        "Best rule-based choices",
                        options=suggested_room_ids,
                        format_func=room_options.get,
                        key="manual_suggested_assignment_room"
                    )
                else:
                    suggested_room_id = None
                    st.info(
                        "No currently available room satisfies all of this "
                        "dog's normal assignment rules."
                    )

                use_other_room = st.checkbox(
                    "Choose from all open rooms",
                    value=not bool(suggested_room_ids),
                    key="manual_use_other_room"
                )

                if use_other_room:
                    st.markdown("#### All Open Rooms")

                    if other_room_ids:
                        selected_room_id = st.selectbox(
                            "Override destination",
                            options=other_room_ids,
                            format_func=room_options.get,
                            key="manual_other_assignment_room"
                        )
                    else:
                        selected_room_id = None
                        st.warning("There are no other open rooms to select.")
                else:
                    selected_room_id = suggested_room_id

                override_reason = ""
                selected_room_is_suggested = (
                    selected_room_id in suggested_room_ids
                    if selected_room_id is not None
                    else False
                )
                requires_override_reason = (
                    use_other_room and not selected_room_is_suggested
                )

                if requires_override_reason:
                    override_reason = st.text_input(
                        "Override Reason *",
                        max_chars=200,
                        placeholder=(
                            "Explain why a non-suggested room is needed"
                        ),
                        key="manual_assignment_reason"
                    )

                destination_occupants = [
                    occupant
                    for occupant in occupied_by_room.get(
                        selected_room_id,
                        []
                    )
                    if int(occupant["dog_id"]) not in {
                        int(record["dog_id"])
                        for record in moving_records
                    }
                ]

                if any(
                    occupant.get("locked", False)
                    for occupant in destination_occupants
                ):
                    st.error(
                        "That room is reserved by a boarding dog and cannot "
                        "be overridden from the nap assignment page."
                    )
                    destination_blocked = True
                else:
                    destination_blocked = False

                relocation_plans = []
                relocation_reasons_missing = False

                if destination_occupants and not destination_blocked:
                    st.warning(
                        "This room is occupied. Choose where to move "
                        + ", ".join(
                            occupant["dog_name"]
                            for occupant in destination_occupants
                        )
                        + " before saving."
                    )
                    st.markdown("#### Move Current Occupants")

                    relocation_room_ids = sorted(
                        [
                            room_id
                            for room_id in room_options
                            if room_id != selected_room_id
                            and not any(
                                int(room_occupant["dog_id"])
                                != selected_dog_id
                                for room_occupant in occupied_by_room.get(
                                    room_id, []
                                )
                            )
                        ],
                        key=lambda room_id: room_sort_key(
                            rooms_df[
                                rooms_df["room_id"].astype(int) == room_id
                            ].iloc[0].to_dict()
                        )
                    )

                    if not relocation_room_ids:
                        st.error(
                            "There is no empty open room available for the "
                            "current occupant."
                        )
                        destination_blocked = True

                    for occupant in destination_occupants:
                        occupant_id = int(occupant["dog_id"])
                        occupant_suggestions = {
                            int(room_id)
                            for room_id in suggestion_lookup.get(
                                occupant_id,
                                suggestion_lookup.get(str(occupant_id), [])
                            )
                        }
                        suggested_relocation_ids = [
                            room_id
                            for room_id in relocation_room_ids
                            if room_id in occupant_suggestions
                        ]

                        if relocation_room_ids:
                            st.markdown(
                                f'##### Suggested Rooms for '
                                f'{occupant["dog_name"]}'
                            )

                            if suggested_relocation_ids:
                                suggested_relocation_room_id = st.selectbox(
                                    f'Best choices for {occupant["dog_name"]}',
                                    options=suggested_relocation_ids,
                                    format_func=room_options.get,
                                    key=(
                                        "relocate_suggested_occupant_"
                                        f"{occupant_id}"
                                    )
                                )
                            else:
                                suggested_relocation_room_id = None
                                st.info(
                                    f'No empty suggested rooms are available '
                                    f'for {occupant["dog_name"]}.'
                                )

                            use_all_relocation_rooms = st.checkbox(
                                f'Choose from all open rooms for '
                                f'{occupant["dog_name"]}',
                                value=not bool(suggested_relocation_ids),
                                disabled=not bool(suggested_relocation_ids),
                                key=(
                                    "relocate_use_all_rooms_"
                                    f"{occupant_id}"
                                )
                            )

                            if use_all_relocation_rooms:
                                relocation_room_id = st.selectbox(
                                    f'All open rooms for '
                                    f'{occupant["dog_name"]}',
                                    options=relocation_room_ids,
                                    format_func=room_options.get,
                                    key=f"relocate_occupant_{occupant_id}"
                                )
                            else:
                                relocation_room_id = (
                                    suggested_relocation_room_id
                                )

                            relocation_is_suggested = (
                                relocation_room_id in occupant_suggestions
                                if relocation_room_id is not None
                                else False
                            )
                            relocation_reason = ""

                            if not relocation_is_suggested:
                                relocation_reason = st.text_input(
                                    f'Override reason for {occupant["dog_name"]} *',
                                    max_chars=200,
                                    key=(
                                        "relocate_occupant_reason_"
                                        f"{occupant_id}"
                                    )
                                )
                                relocation_reasons_missing = (
                                    relocation_reasons_missing
                                    or not relocation_reason.strip()
                                )

                            relocation_plans.append(
                                {
                                    "assignment": occupant,
                                    "room_id": relocation_room_id,
                                    "is_suggested": relocation_is_suggested,
                                    "reason": relocation_reason.strip()
                                }
                            )

                if st.button(
                    (
                        "Move Siblings Together"
                        if sibling_move_mode == "Move Together"
                        else "Move Dog"
                    ),
                    type="primary",
                    disabled=(
                        destination_blocked or selected_room_id is None
                    ),
                    use_container_width=True,
                    key="move_assignment_dog"
                ):
                    if (
                        requires_override_reason
                        and not override_reason.strip()
                    ):
                        st.error("An override reason is required.")
                    elif (
                        sibling_move_mode == "Separate — Override"
                        and not sibling_override_reason.strip()
                    ):
                        st.error(
                            "A sibling separation reason is required."
                        )
                    elif relocation_reasons_missing:
                        st.error(
                            "Enter an override reason for every displaced "
                            "dog using a non-suggested room."
                        )
                    elif len({
                        plan["room_id"]
                        for plan in relocation_plans
                    }) != len(relocation_plans):
                        st.error(
                            "Choose a different destination for each dog "
                            "being moved."
                        )
                    else:
                        source = selected_source
                        dog_id = selected_dog_id
                        destination = rooms_df[
                            rooms_df["room_id"].astype(int)
                            == selected_room_id
                        ].iloc[0]

                        assignments_to_move = []
                        moving_dog_ids = {
                            int(record["dog_id"])
                            for record in moving_records
                        }

                        for record in moving_records:
                            record_id = int(record["dog_id"])
                            existing_assignment = next(
                                (
                                    item
                                    for item in draft
                                    if int(item["dog_id"]) == record_id
                                ),
                                None
                            )
                            if existing_assignment is None:
                                existing_assignment = {
                                    **record,
                                    "locked": False
                                }
                                draft.append(existing_assignment)
                            assignments_to_move.append(existing_assignment)

                        unassigned = [
                            item
                            for item in unassigned
                            if int(item["dog_id"]) not in moving_dog_ids
                        ]

                        for plan in relocation_plans:
                            relocation_destination = rooms_df[
                                rooms_df["room_id"].astype(int)
                                == int(plan["room_id"])
                            ].iloc[0]
                            plan["assignment"].update(
                                {
                                    "room_id": int(
                                        relocation_destination["room_id"]
                                    ),
                                    "room_number": str(
                                        relocation_destination[
                                            "room_number"
                                        ]
                                    ),
                                    "room_name": str(
                                        relocation_destination["room_name"]
                                        or ""
                                    ),
                                    "room_type": str(
                                        relocation_destination["room_type"]
                                        or ""
                                    ),
                                    "assignment_type": (
                                        "Manual Move"
                                        if plan["is_suggested"]
                                        else "Manual Override"
                                    ),
                                    "override_reason": (
                                        None
                                        if plan["is_suggested"]
                                        else plan["reason"]
                                    )
                                }
                            )

                        for assignment in assignments_to_move:
                            is_separation_override = (
                                sibling_move_mode == "Separate — Override"
                            )
                            assignment.update(
                                {
                                    "room_id": int(destination["room_id"]),
                                    "room_number": str(
                                        destination["room_number"]
                                    ),
                                    "room_name": str(
                                        destination["room_name"] or ""
                                    ),
                                    "room_type": str(
                                        destination["room_type"] or ""
                                    ),
                                    "assignment_type": (
                                        "Manual Override"
                                        if requires_override_reason
                                        or is_separation_override
                                        else "Manual Move"
                                    ),
                                    "override_reason": (
                                        sibling_override_reason.strip()
                                        if is_separation_override
                                        else override_reason.strip()
                                        if requires_override_reason
                                        else None
                                    )
                                }
                            )
                        st.session_state["assignment_draft"] = draft
                        st.session_state["assignment_unassigned"] = unassigned
                        moved_names = ", ".join(
                            item["dog_name"]
                            for item in assignments_to_move
                        )
                        moved_verb = (
                            "was" if len(assignments_to_move) == 1 else "were"
                        )
                        st.session_state["assignment_notice"] = (
                            f"{moved_names} {moved_verb} moved to "
                            f'{room_label(destination.to_dict())}.'
                        )
                        st.rerun()

        st.write("")
        unassigned_container = st.expander(
            f"Unassigned Dogs — {len(unassigned)}",
            expanded=bool(unassigned)
        )

        with unassigned_container:
            if not unassigned:
                st.success("Every daycare dog has a draft assignment.")
            else:
                unassigned_df = pd.DataFrame(unassigned)[
                    ["dog_name", "play_group", "size_class", "reason"]
                ].rename(
                    columns={
                        "dog_name": "Dog Name",
                        "play_group": "Play Group",
                        "size_class": "Size",
                        "reason": "Reason"
                    }
                )
                st.dataframe(
                    unassigned_df,
                    use_container_width=True,
                    hide_index=True
                )

        finalize_container = st.container(border=True)

        with finalize_container:
            editing_finalized = st.session_state.get(
                "assignment_editing_finalized",
                False
            )
            st.subheader(
                (
                    "Save Updated Assignments"
                    if editing_finalized
                    else "Finalize Today's Assignments"
                ),
                anchor=False
            )
            st.caption(
                "Finalizing saves this draft to Daily Records. Boarding "
                "reservations remain protected."
            )

            st.markdown("#### Space Remaining After This Draft")
            crate_space_df, room_space_df = remaining_space_tables(
                draft,
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
                "Shared siblings assigned to one room count as one occupied "
                "space. Closed rooms are not included."
            )
            confirm_finalize = st.checkbox(
                "I reviewed today's assignments",
                key="confirm_finalize_assignments"
            )
            confirm_unassigned = True
            update_reason = None

            if editing_finalized:
                update_reason = st.text_input(
                    "Update Reason *",
                    max_chars=200,
                    placeholder=(
                        "Example: Late arrival added after 9:30 AM"
                    ),
                    key="assignment_update_reason"
                )

            if unassigned:
                confirm_unassigned = st.checkbox(
                    "Finalize even though dogs remain unassigned",
                    key="confirm_unassigned_assignments"
                )

            if st.button(
                (
                    "Save Updated Assignments"
                    if editing_finalized
                    else "Finalize and Save Today's Assignments"
                ),
                type="primary",
                disabled=not (
                    confirm_finalize
                    and confirm_unassigned
                    and (
                        not editing_finalized
                        or bool(str(update_reason or "").strip())
                    )
                ),
                use_container_width=True,
                key="finalize_assignments"
            ):
                try:
                    save_result = save_daily_assignments(
                        draft,
                        update_reason=update_reason
                    )
                except Exception:
                    st.error(
                        "Assignments could not be finalized. No assignment "
                        "records were changed."
                    )
                else:
                    st.session_state.pop("assignment_draft", None)
                    st.session_state.pop("assignment_unassigned", None)
                    st.session_state.pop(
                        "assignment_room_suggestions",
                        None
                    )
                    st.session_state.pop(
                        "assignment_editing_finalized",
                        None
                    )
                    st.session_state["assignment_notice"] = (
                        f'Finalized revision '
                        f'{save_result["revision_number"]} with '
                        f'{save_result["saved_count"]} assignments.'
                    )
                    st.rerun()
