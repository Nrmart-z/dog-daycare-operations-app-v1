import pandas as pd
import streamlit as st

from database import (
    add_dog_profile,
    load_all_dogs,
    load_sibling_group,
    set_dog_active_status,
    update_dog_profile
)


def yes_or_no(value):

    try:
        return "Yes" if int(value) > 0 else "No"
    except (TypeError, ValueError):
        return "No"


def allowed_or_not(value):

    return "Allowed" if yes_or_no(value) == "Yes" else "Not allowed"


def display_value(value, fallback="Not provided"):

    if pd.isna(value) or str(value).strip() in {"", "None", "nan"}:
        return fallback

    return str(value)


def format_gender(value):

    gender = str(value).strip().upper()

    if gender in {"M", "MALE"}:
        return "Male"
    if gender in {"F", "FEMALE"}:
        return "Female"
    return display_value(value)


def show_crew_dog_records():
    """Read-only directory of every dog profile on record."""
    dogs = load_all_dogs().copy()
    st.title("Dog Records")
    st.caption("Read-only directory · Dog profiles cannot be changed here")
    if dogs.empty:
        st.info("There are no dog records yet.")
        return

    search = st.text_input(
        "Search dogs", placeholder="Search by name, nickname, or breed"
    ).strip()
    if search:
        matches = pd.Series(False, index=dogs.index)
        for column in ("dog_name", "dog_nickname", "dog_breed"):
            if column in dogs.columns:
                matches |= dogs[column].fillna("").astype(str).str.contains(
                    search, case=False, regex=False
                )
        dogs = dogs[matches]

    display_columns = [
        column for column in (
            "dog_name", "dog_nickname", "dog_breed", "gender",
            "play_group", "crate_training", "active_status",
        ) if column in dogs.columns
    ]
    directory = dogs[display_columns].copy()
    if "gender" in directory:
        directory["gender"] = directory["gender"].map(format_gender)
    if "crate_training" in directory:
        directory["crate_training"] = directory["crate_training"].map(yes_or_no)
    if "active_status" in directory:
        directory["active_status"] = directory["active_status"].map(
            lambda value: "Active" if yes_or_no(value) == "Yes" else "Inactive"
        )
    directory = directory.rename(columns={
        "dog_name": "Dog Name",
        "dog_nickname": "Nickname",
        "dog_breed": "Breed",
        "gender": "Gender",
        "play_group": "Play Group",
        "crate_training": "Crate Trained",
        "active_status": "Status",
    })
    st.metric("Dogs on Record", len(directory))
    if directory.empty:
        st.info("No dog records match that search.")
    else:
        st.dataframe(directory, use_container_width=True, hide_index=True)


def format_priority(value):

    if pd.isna(value):
        return "Not set"

    try:
        priority = int(value)
    except (TypeError, ValueError):
        return "Not set"

    return str(priority) if priority > 0 else "Cannot use"


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


def format_shared_room(rule, allowed_field, priority_field):

    if yes_or_no(rule[allowed_field]) != "Yes":
        return "Cannot share"

    priority = int(rule[priority_field] or 0)

    if priority == 0:
        return "Cannot share"

    return f"Allowed — Priority {priority}"


def clear_profile_search_after_selection():

    if st.session_state.get("dog_management_profile") is not None:
        st.session_state["dog_management_search"] = ""


def keep_dog_management_section_open(section_key):

    st.session_state[section_key] = True


def show_dog_management():

    dogs_df = load_all_dogs()
    sibling_groups_df = load_sibling_group()

    st.title("Dog Management")
    st.caption("Search and review dog profiles, permissions, and preferences")

    notice = st.session_state.pop("dog_management_notice", None)

    if notice:
        st.success(notice)

    st.write("")

    st.markdown(
        '<span class="prominent-action-marker add-new-dog-marker"></span>',
        unsafe_allow_html=True
    )
    with st.expander(
        "Add New Dog",
        expanded=st.session_state.get("add_new_dog_open", False)
    ):
        st.caption(
            "Create a permanent dog profile. The dog will be Active and "
            "available to add to Attendance after it is saved."
        )

        st.markdown("##### Sibling Relationship")
        sibling_options = {None: "No registered sibling"}
        sibling_options.update(
            {
                int(row["dog_id"]): (
                    f'{row["dog_name"]} — '
                    + (
                        "Brother"
                        if str(row["gender"]).strip().upper() == "M"
                        else "Sister"
                    )
                )
                for _, row in dogs_df.sort_values(
                    by="dog_name",
                    key=lambda column: column.str.lower()
                ).iterrows()
            }
        )
        new_sibling_id = st.selectbox(
            "Existing Sibling",
            options=list(sibling_options),
            format_func=sibling_options.get,
            help=(
                "Select a sibling whose permanent profile is already "
                "in Dog Management."
            ),
            key="new_dog_existing_sibling",
            on_change=keep_dog_management_section_open,
            args=("add_new_dog_open",)
        )

        if new_sibling_id is not None:
            new_keep_together = st.checkbox(
                "Keep siblings together when possible",
                value=True,
                key="new_dog_keep_siblings_together",
                on_change=keep_dog_management_section_open,
                args=("add_new_dog_open",)
            )
        else:
            new_keep_together = False

        with st.form("add_new_dog_form", clear_on_submit=True):
            st.markdown("##### Basic Information")
            row = st.columns(2)
            new_name = row[0].text_input(
                "Dog Name *", max_chars=50
            )
            new_nickname = row[1].text_input(
                "Nickname", max_chars=50
            )

            row = st.columns(2)
            new_breed = row[0].text_input("Breed", max_chars=30)
            new_color = row[1].text_input("Color", max_chars=50)

            row = st.columns(4)
            new_gender = row[0].selectbox(
                "Gender *",
                ["M", "F"],
                format_func=lambda value: (
                    "Male" if value == "M" else "Female"
                )
            )
            new_birth_date = row[1].date_input(
                "Date of Birth", value=None, format="MM/DD/YYYY"
            )
            new_size_class = row[2].selectbox(
                "Size Class *", ["Small", "Medium", "Big"]
            )
            new_play_group = row[3].selectbox(
                "Play Group *", ["Big", "Small", "Separate"]
            )

            st.markdown("##### Room Permissions")
            row = st.columns(4)
            new_crate_allowed = row[0].checkbox("Crate allowed")
            new_kennel_allowed = row[1].checkbox("Kennel allowed")
            new_suite_allowed = row[2].checkbox("Suite allowed")
            new_floor_allowed = row[3].checkbox("Floor allowed")

            st.caption(
                "Crate-trained status is automatically the same as "
                "Crate allowed."
            )
            row = st.columns(2)
            new_larger_crate = row[0].checkbox(
                "One larger crate allowed"
            )
            new_crate_size = row[1].selectbox(
                "Crate Size *",
                ["Not set", "XS", "SM", "M", "L", "XL", "XXL"],
                help="Required whenever Crate allowed is checked."
            )

            st.markdown("##### Nap-Time Priorities")
            st.caption(
                "0 = Cannot use · 1 = Highest priority · "
                "4 = Lowest priority"
            )
            row = st.columns(4)
            new_crate_priority = row[0].number_input(
                "Crate Priority", 0, 4, 0
            )
            new_kennel_priority = row[1].number_input(
                "Kennel Priority", 0, 4, 0
            )
            new_suite_priority = row[2].number_input(
                "Suite Priority", 0, 4, 0
            )
            new_floor_priority = row[3].number_input(
                "Floor Priority", 0, 4, 0
            )

            st.markdown("##### Safety and Notes")
            row = st.columns(2)
            new_fence_fighter = row[0].checkbox("Fence fighter")
            new_fence_jumper = row[1].checkbox("Fence jumper")
            new_notes = st.text_area("Notes", max_chars=200)

            if new_sibling_id is not None and new_keep_together:
                st.markdown("##### Shared Sibling Placement")
                st.caption(
                    "Employees can still override and separate siblings "
                    "during an assignment when necessary."
                )

                shared_columns = st.columns(3)
                new_shared_suite = shared_columns[0].checkbox(
                    "Can share a suite"
                )
                new_shared_floor = shared_columns[1].checkbox(
                    "Can share a floor room"
                )
                new_shared_kennel = shared_columns[2].checkbox(
                    "Can share a kennel"
                )

                st.caption(
                    "Sibling priority: 0 = Cannot share · "
                    "1 = Highest priority · 3 = Lowest priority"
                )
                priority_columns = st.columns(3)
                new_shared_suite_priority = priority_columns[0].number_input(
                    "Shared Suite Priority", 0, 3, 0
                )
                new_shared_floor_priority = priority_columns[1].number_input(
                    "Shared Floor Priority", 0, 3, 0
                )
                new_shared_kennel_priority = priority_columns[2].number_input(
                    "Shared Kennel Priority", 0, 3, 0
                )
            else:
                new_shared_suite = False
                new_shared_floor = False
                new_shared_kennel = False
                new_shared_suite_priority = 0
                new_shared_floor_priority = 0
                new_shared_kennel_priority = 0

            save_new_dog = st.form_submit_button(
                "Add Dog",
                type="primary",
                use_container_width=True
            )

            if save_new_dog:
                try:
                    new_dog_id = add_dog_profile(
                        {
                            "dog_name": new_name,
                            "dog_nickname": new_nickname,
                            "dog_breed": new_breed,
                            "color": new_color,
                            "gender": new_gender,
                            "date_of_birth": new_birth_date,
                            "size_class": new_size_class,
                            "play_group": new_play_group,
                            "crate_allowed": new_crate_allowed,
                            "kennel_allowed": new_kennel_allowed,
                            "suite_allowed": new_suite_allowed,
                            "floor_allowed": new_floor_allowed,
                            "crate_trained": new_crate_allowed,
                            "larger_crate_allowed": new_larger_crate,
                            "crate_size": (
                                None
                                if new_crate_size == "Not set"
                                else new_crate_size
                            ),
                            "crate_priority": new_crate_priority,
                            "kennel_priority": new_kennel_priority,
                            "suite_priority": new_suite_priority,
                            "floor_priority": new_floor_priority,
                            "fence_fighter": new_fence_fighter,
                            "fence_jumpers": new_fence_jumper,
                            "Notes": new_notes,
                            "sibling_dog_id": new_sibling_id,
                            "keep_together": new_keep_together,
                            "shared_suite_allowed": new_shared_suite,
                            "shared_floor_allowed": new_shared_floor,
                            "shared_kennel_allowed": new_shared_kennel,
                            "shared_suite_priority": (
                                new_shared_suite_priority
                            ),
                            "shared_floor_priority": (
                                new_shared_floor_priority
                            ),
                            "shared_kennel_priority": (
                                new_shared_kennel_priority
                            )
                        }
                    )
                except (ValueError, TypeError) as error:
                    st.error(str(error))
                except Exception:
                    st.error(
                        "The new dog profile could not be created. "
                        "Please try again."
                    )
                else:
                    st.session_state["dog_management_notice"] = (
                        f"{new_name.strip()} was added successfully "
                        f"(Dog ID {new_dog_id})."
                    )
                    st.rerun()

    st.write("")

    if dogs_df.empty:
        st.info("No dog profiles were found.")
        return

    directory = st.container(border=True)

    with directory:
        st.subheader("Dog Directory", anchor=False)

        summary_columns = st.columns(5)
        active_dogs_df = dogs_df[dogs_df["active_status"].astype(int) == 1]
        inactive_dogs_df = dogs_df[dogs_df["active_status"].astype(int) == 0]
        summary_columns[0].metric("Active Dogs", len(active_dogs_df))
        summary_columns[1].metric(
            "Big Play Group Dogs",
            len(active_dogs_df[active_dogs_df["play_group"] == "Big"])
        )
        summary_columns[2].metric(
            "Small Play Group Dogs",
            len(active_dogs_df[active_dogs_df["play_group"] == "Small"])
        )
        summary_columns[3].metric(
            "Separate Dogs",
            len(
                active_dogs_df[
                    active_dogs_df["play_group"] == "Separate"
                ]
            )
        )
        summary_columns[4].metric(
            "Inactive Dogs",
            len(inactive_dogs_df)
        )

        filters = st.columns([2, 1, 1])
        search = filters[0].text_input(
            "Search Dogs",
            placeholder="Search by name, nickname, or breed...",
            key="dog_management_search"
        )
        status_filter = filters[1].selectbox(
            "Profile Status",
            ["Active", "Inactive", "All"],
            key="dog_management_status_filter"
        )
        play_group_filter = filters[2].selectbox(
            "Play Group",
            ["All", "Small", "Separate", "Big"],
            key="dog_management_play_group_filter"
        )

        filtered_dogs_df = dogs_df.copy()

        if status_filter != "All":
            desired_status = 1 if status_filter == "Active" else 0
            filtered_dogs_df = filtered_dogs_df[
                filtered_dogs_df["active_status"].astype(int)
                == desired_status
            ].copy()

        if play_group_filter != "All":
            filtered_dogs_df = filtered_dogs_df[
                filtered_dogs_df["play_group"] == play_group_filter
            ].copy()

        if search:
            search_mask = (
                filtered_dogs_df["dog_name"].str.contains(
                    search, case=False, na=False
                )
                | filtered_dogs_df["dog_nickname"].fillna("").str.contains(
                    search, case=False, na=False
                )
                | filtered_dogs_df["dog_breed"].fillna("").str.contains(
                    search, case=False, na=False
                )
            )
            filtered_dogs_df = filtered_dogs_df[search_mask].copy()

        directory_df = filtered_dogs_df[
            [
                "dog_name",
                "dog_nickname",
                "dog_breed",
                "gender",
                "size_class",
                "play_group",
                "active_status"
            ]
        ].rename(
            columns={
                "dog_name": "Dog Name",
                "dog_nickname": "Nickname",
                "dog_breed": "Breed",
                "gender": "Gender",
                "size_class": "Size Class",
                "play_group": "Play Group",
                "active_status": "Status"
            }
        )

        directory_df["Nickname"] = directory_df["Nickname"].fillna("")
        directory_df["Gender"] = directory_df["Gender"].map(format_gender)
        directory_df["Status"] = directory_df["Status"].map(
            lambda value: "Active" if int(value) == 1 else "Inactive"
        )
        directory_df = directory_df.sort_values(
            by="Dog Name",
            key=lambda column: column.str.lower()
        ).reset_index(drop=True)

        st.caption(f"{len(directory_df)} dog(s) shown")

        if directory_df.empty:
            st.info("No dogs matched that search.")
            return

        st.dataframe(
            directory_df.style.apply(highlight_play_group, axis=1),
            use_container_width=True,
            hide_index=True,
            height=360
        )

    st.write("")

    profile = st.container(border=True)

    with profile:
        st.subheader("Dog Profile", anchor=False)

        profile_options = {
            None: "Select a dog...",
            **{
            int(row["dog_id"]): (
                f'{row["dog_name"]}'
                + (
                    f' | Nickname: {row["dog_nickname"]}'
                    if pd.notna(row["dog_nickname"])
                    and str(row["dog_nickname"]).strip()
                    else ""
                )
                + f' | {row["dog_breed"]}'
            )
            for _, row in filtered_dogs_df.sort_values(
                by="dog_name",
                key=lambda column: column.str.lower()
            ).iterrows()
            }
        }

        selected_dog_id = st.selectbox(
            "Select Dog",
            options=list(profile_options),
            format_func=profile_options.get,
            key="dog_management_profile",
            on_change=clear_profile_search_after_selection
        )

        if selected_dog_id is None:
            st.info(
                "Search above or select a dog to view and edit a profile."
            )
            return

        dog = dogs_df[
            dogs_df["dog_id"].astype(int) == selected_dog_id
        ].iloc[0]

        st.markdown(f'### {dog["dog_name"]}')

        is_active = int(dog["active_status"]) == 1
        if is_active:
            st.success("Active profile — available for attendance.")
        else:
            st.warning(
                "Inactive profile — unavailable for Daycare or Boarding "
                "attendance until reactivated."
            )

        if pd.notna(dog["dog_nickname"]) and str(
            dog["dog_nickname"]
        ).strip():
            st.caption(f'Nickname: {dog["dog_nickname"]}')

        identity = st.container(border=True)
        with identity:
            st.markdown("#### Identity")
            columns = st.columns(4)
            columns[0].markdown(
                f'**Breed:** {display_value(dog["dog_breed"])}'
            )
            columns[1].markdown(
                f'**Color:** {display_value(dog["color"])}'
            )
            columns[2].markdown(
                f'**Gender:** {format_gender(dog["gender"])}'
            )
            columns[3].markdown(
                f'**Date of Birth:** {display_value(dog["date_of_birth"])}'
            )

            columns = st.columns(4)
            columns[0].markdown(
                f'**Size Class:** {display_value(dog["size_class"])}'
            )
            columns[1].markdown(
                f'**Play Group:** {display_value(dog["play_group"])}'
            )
            columns[2].markdown(
                f'**Owner ID:** {display_value(dog["owner_id"])}'
            )
            columns[3].markdown(
                f'**Dog ID:** {display_value(dog["dog_id"])}'
            )

        st.write("")

        permissions = st.container(border=True)
        with permissions:
            st.markdown("#### Room Permissions")
            columns = st.columns(4)
            columns[0].markdown(
                f'**Crate:** {allowed_or_not(dog["crate_allowed"])}'
            )
            columns[1].markdown(
                f'**Kennel:** {allowed_or_not(dog["kennel_allowed"])}'
            )
            columns[2].markdown(
                f'**Suite:** {allowed_or_not(dog["suite_allowed"])}'
            )
            columns[3].markdown(
                f'**Floor:** {allowed_or_not(dog["floor_allowed"])}'
            )

            columns = st.columns(4)
            columns[0].markdown(
                f'**Crate Trained:** {yes_or_no(dog["crate_trained"])}'
            )
            columns[1].markdown(
                f'**Crate Size:** '
                f'{display_value(dog["crate_size"], "Not applicable")}'
            )
            columns[2].markdown(
                f'**Larger Crate:** '
                f'{allowed_or_not(dog["larger_crate_allowed"])}'
            )
            columns[3].markdown(
                f'**Fence Jumper:** {yes_or_no(dog["fence_jumpers"])}'
            )

        st.write("")

        priorities = st.container(border=True)
        with priorities:
            st.markdown("#### Nap-Time Priorities and Safety")
            columns = st.columns(5)
            priority_fields = [
                ("Crate Priority", "crate_priority"),
                ("Kennel Priority", "kennel_priority"),
                ("Suite Priority", "suite_priority"),
                ("Floor Priority", "floor_priority")
            ]

            for column, (label, field) in zip(
                columns[:4], priority_fields
            ):
                column.markdown(
                    f'**{label}:** {format_priority(dog[field])}'
                )

            columns[4].markdown(
                f'**Fence Fighter:** {yes_or_no(dog["fence_fighter"])}'
            )

        st.write("")

        relationships = st.container(border=True)
        with relationships:
            st.markdown("#### Relationships and Notes")

            sibling_group_id = dog["sibling_group_id"]

            if pd.isna(sibling_group_id):
                st.write("**Sibling Group:** None")
            else:
                siblings = dogs_df[
                    (dogs_df["sibling_group_id"] == sibling_group_id)
                    & (dogs_df["dog_id"] != dog["dog_id"])
                ]["dog_name"].tolist()
                matching_rule = sibling_groups_df[
                    sibling_groups_df["sibling_group_id"]
                    == sibling_group_id
                ]
                placement = "Not specified"

                if not matching_rule.empty:
                    placement = (
                        "Keep together"
                        if yes_or_no(
                            matching_rule.iloc[0]["keep_together"]
                        ) == "Yes"
                        else "Assign separately"
                    )

                st.write(
                    f'**Siblings:** {", ".join(siblings) or "None listed"}'
                )
                st.write(f"**Placement Rule:** {placement}")

            st.write(
                f'**Notes:** {display_value(dog["Notes"], "No notes")}'
            )

        st.write("")

        status_controls = st.container(border=True)
        with status_controls:
            st.markdown("#### Profile Status")

            if is_active:
                st.caption(
                    "Deactivating keeps this profile and all historical "
                    "records, but removes the dog from Attendance search."
                )
                confirm_status_change = st.checkbox(
                    f'Confirm deactivation of {dog["dog_name"]}',
                    key=f"confirm_deactivate_{selected_dog_id}"
                )
                change_status = st.button(
                    "Deactivate Dog",
                    type="secondary",
                    disabled=not confirm_status_change,
                    use_container_width=True,
                    key=f"deactivate_dog_{selected_dog_id}"
                )
                new_status = False
                success_message = (
                    f'{dog["dog_name"]} was deactivated and will no longer '
                    "appear in Attendance."
                )
            else:
                st.caption(
                    "Reactivating makes this dog available to add to "
                    "Daycare or Boarding attendance again."
                )
                change_status = st.button(
                    "Reactivate Dog",
                    type="primary",
                    use_container_width=True,
                    key=f"reactivate_dog_{selected_dog_id}"
                )
                new_status = True
                success_message = (
                    f'{dog["dog_name"]} was reactivated and is now '
                    "available in Attendance."
                )

            if change_status:
                try:
                    changed = set_dog_active_status(
                        selected_dog_id,
                        new_status
                    )
                except Exception:
                    st.error(
                        "The profile status could not be changed. "
                        "Please try again."
                    )
                else:
                    if changed:
                        st.session_state["dog_management_notice"] = (
                            success_message
                        )
                        st.rerun()
                    else:
                        st.info("The profile status was already up to date.")

        st.write("")

        editor = st.container(
            key="dog_profile_editor"
        )

        with editor, st.expander(
            "Edit Profile",
            expanded=st.session_state.get("edit_dog_profile_open", False)
        ):
            st.caption(
                "Changes are not saved until Apply Changes is selected. "
                "Sibling placement rules apply to the entire sibling group."
            )

            sibling_group_id = (
                None
                if pd.isna(dog["sibling_group_id"])
                else int(dog["sibling_group_id"])
            )
            sibling_rule = None
            sibling_names = []

            if sibling_group_id is not None:
                matching_rules = sibling_groups_df[
                    sibling_groups_df["sibling_group_id"].astype(int)
                    == sibling_group_id
                ]

                if not matching_rules.empty:
                    sibling_rule = matching_rules.iloc[0]
                    sibling_names = [
                        str(sibling["dog_name"])
                        for _, sibling in dogs_df[
                            (
                                dogs_df["sibling_group_id"]
                                == sibling_group_id
                            )
                            & (
                                dogs_df["dog_id"].astype(int)
                                != selected_dog_id
                            )
                        ].sort_values(
                            by="dog_name",
                            key=lambda column: column.str.lower()
                        ).iterrows()
                    ]

            sibling_widget_keys = [
                f"edit_keep_together_{selected_dog_id}",
                f"edit_shared_suite_{selected_dog_id}",
                f"edit_shared_floor_{selected_dog_id}",
                f"edit_shared_kennel_{selected_dog_id}",
                f"edit_shared_suite_priority_{selected_dog_id}",
                f"edit_shared_floor_priority_{selected_dog_id}",
                f"edit_shared_kennel_priority_{selected_dog_id}"
            ]

            if sibling_rule is not None:
                st.markdown("##### Sibling Settings")
                st.write(
                    "**Sibling group:** "
                    + (", ".join(sibling_names) or "No other dog listed")
                )
                edited_keep_together = st.checkbox(
                    "Keep siblings together when possible",
                    value=yes_or_no(
                        sibling_rule["keep_together"]
                    ) == "Yes",
                    key=f"edit_keep_together_{selected_dog_id}",
                    on_change=keep_dog_management_section_open,
                    args=("edit_dog_profile_open",)
                )

                if edited_keep_together:
                    st.caption(
                        "0 = Cannot share · 1 = Highest priority · "
                        "3 = Lowest priority"
                    )
                    shared_columns = st.columns(3)

                    def sibling_priority(field):
                        value = sibling_rule[field]
                        return 0 if pd.isna(value) else int(value)

                    edited_shared_suite_priority = (
                        shared_columns[0].number_input(
                            "Shared Suite Priority",
                            min_value=0,
                            max_value=3,
                            value=sibling_priority(
                                "shared_suite_priority"
                            ),
                            step=1,
                            key=(
                                f"edit_shared_suite_priority_"
                                f"{selected_dog_id}"
                            ),
                            on_change=keep_dog_management_section_open,
                            args=("edit_dog_profile_open",)
                        )
                    )
                    edited_shared_floor_priority = (
                        shared_columns[1].number_input(
                            "Shared Floor Priority",
                            min_value=0,
                            max_value=3,
                            value=sibling_priority(
                                "shared_floor_priority"
                            ),
                            step=1,
                            key=(
                                f"edit_shared_floor_priority_"
                                f"{selected_dog_id}"
                            ),
                            on_change=keep_dog_management_section_open,
                            args=("edit_dog_profile_open",)
                        )
                    )
                    edited_shared_kennel_priority = (
                        shared_columns[2].number_input(
                            "Shared Kennel Priority",
                            min_value=0,
                            max_value=3,
                            value=sibling_priority(
                                "shared_kennel_priority"
                            ),
                            step=1,
                            key=(
                                f"edit_shared_kennel_priority_"
                                f"{selected_dog_id}"
                            ),
                            on_change=keep_dog_management_section_open,
                            args=("edit_dog_profile_open",)
                        )
                    )
                else:
                    edited_shared_suite_priority = 0
                    edited_shared_floor_priority = 0
                    edited_shared_kennel_priority = 0
                    st.info(
                        "These siblings will be assigned separately. "
                        "Shared-room permissions and priorities will be "
                        "removed when changes are applied."
                    )
            else:
                edited_keep_together = False
                edited_shared_suite_priority = 0
                edited_shared_floor_priority = 0
                edited_shared_kennel_priority = 0

            size_options = list(
                dict.fromkeys(
                    [
                        str(dog["size_class"]),
                        "Small",
                        "Medium",
                        "Big"
                    ]
                )
            )
            crate_size_options = list(
                dict.fromkeys(
                    [
                        display_value(dog["crate_size"], "Not set"),
                        "Not set",
                        "XS",
                        "SM",
                        "M",
                        "L",
                        "XL",
                        "XXL"
                    ]
                )
            )
            current_gender = str(dog["gender"]).strip().upper()
            gender_options = ["M", "F"]

            with st.form(
                f"edit_dog_form_{selected_dog_id}",
                clear_on_submit=True
            ):
                st.markdown("##### Basic Information")
                row = st.columns(2)
                edited_name = row[0].text_input(
                    "Dog Name",
                    value=str(dog["dog_name"]),
                    max_chars=50
                )
                edited_nickname = row[1].text_input(
                    "Nickname",
                    value=(
                        ""
                        if pd.isna(dog["dog_nickname"])
                        else str(dog["dog_nickname"])
                    ),
                    max_chars=50
                )

                row = st.columns(2)
                edited_breed = row[0].text_input(
                    "Breed",
                    value=(
                        ""
                        if pd.isna(dog["dog_breed"])
                        else str(dog["dog_breed"])
                    ),
                    max_chars=30
                )
                edited_color = row[1].text_input(
                    "Color",
                    value=(
                        ""
                        if pd.isna(dog["color"])
                        else str(dog["color"])
                    ),
                    max_chars=50
                )

                row = st.columns(4)
                edited_gender = row[0].selectbox(
                    "Gender",
                    gender_options,
                    index=(
                        gender_options.index(current_gender)
                        if current_gender in gender_options
                        else 0
                    ),
                    format_func=lambda value: (
                        "Male" if value == "M" else "Female"
                    )
                )
                edited_birth_date = row[1].date_input(
                    "Date of Birth",
                    value=(
                        None
                        if pd.isna(dog["date_of_birth"])
                        else dog["date_of_birth"]
                    ),
                    format="MM/DD/YYYY"
                )
                edited_size_class = row[2].selectbox(
                    "Size Class",
                    size_options,
                    index=0
                )
                edited_play_group = row[3].selectbox(
                    "Play Group",
                    ["Big", "Small", "Separate"],
                    index=["Big", "Small", "Separate"].index(
                        str(dog["play_group"])
                    )
                )

                st.markdown("##### Room Permissions")
                row = st.columns(4)
                edited_crate_allowed = row[0].checkbox(
                    "Crate allowed",
                    value=yes_or_no(dog["crate_allowed"]) == "Yes"
                )
                edited_kennel_allowed = row[1].checkbox(
                    "Kennel allowed",
                    value=yes_or_no(dog["kennel_allowed"]) == "Yes"
                )
                edited_suite_allowed = row[2].checkbox(
                    "Suite allowed",
                    value=yes_or_no(dog["suite_allowed"]) == "Yes"
                )
                edited_floor_allowed = row[3].checkbox(
                    "Floor allowed",
                    value=yes_or_no(dog["floor_allowed"]) == "Yes"
                )

                st.caption(
                    "Crate-trained status automatically matches "
                    "Crate allowed."
                )
                row = st.columns(2)
                edited_larger_crate = row[0].checkbox(
                    "One larger crate allowed",
                    value=(
                        yes_or_no(dog["larger_crate_allowed"]) == "Yes"
                    )
                )
                edited_crate_size = row[1].selectbox(
                    "Crate Size *",
                    crate_size_options,
                    index=0,
                    help="Required whenever Crate allowed is checked."
                )

                st.markdown("##### Room Priorities")
                st.caption(
                    "0 = Cannot use · 1 = Highest priority · "
                    "4 = Lowest priority"
                )
                row = st.columns(4)

                def current_priority(field):
                    return (
                        0
                        if pd.isna(dog[field])
                        else int(dog[field])
                    )

                edited_crate_priority = row[0].number_input(
                    "Crate Priority",
                    min_value=0,
                    max_value=4,
                    value=current_priority("crate_priority"),
                    step=1
                )
                edited_kennel_priority = row[1].number_input(
                    "Kennel Priority",
                    min_value=0,
                    max_value=4,
                    value=current_priority("kennel_priority"),
                    step=1
                )
                edited_suite_priority = row[2].number_input(
                    "Suite Priority",
                    min_value=0,
                    max_value=4,
                    value=current_priority("suite_priority"),
                    step=1
                )
                edited_floor_priority = row[3].number_input(
                    "Floor Priority",
                    min_value=0,
                    max_value=4,
                    value=current_priority("floor_priority"),
                    step=1
                )

                st.markdown("##### Safety and Notes")
                row = st.columns(2)
                edited_fence_fighter = row[0].checkbox(
                    "Fence fighter",
                    value=yes_or_no(dog["fence_fighter"]) == "Yes"
                )
                edited_fence_jumper = row[1].checkbox(
                    "Fence jumper",
                    value=yes_or_no(dog["fence_jumpers"]) == "Yes"
                )
                edited_notes = st.text_area(
                    "Notes",
                    value=(
                        ""
                        if pd.isna(dog["Notes"])
                        else str(dog["Notes"])
                    ),
                    max_chars=200
                )

                action_columns = st.columns(2)
                apply_changes = action_columns[0].form_submit_button(
                    "Apply Changes",
                    type="primary",
                    use_container_width=True
                )
                discard_changes = action_columns[1].form_submit_button(
                    "Discard Changes",
                    type="secondary",
                    use_container_width=True
                )

                if apply_changes:
                    try:
                        updated = update_dog_profile(
                            selected_dog_id,
                            {
                                "dog_name": edited_name,
                                "dog_nickname": edited_nickname,
                                "dog_breed": edited_breed,
                                "color": edited_color,
                                "gender": edited_gender,
                                "date_of_birth": edited_birth_date,
                                "size_class": edited_size_class,
                                "play_group": edited_play_group,
                                "crate_allowed": edited_crate_allowed,
                                "kennel_allowed": edited_kennel_allowed,
                                "suite_allowed": edited_suite_allowed,
                                "floor_allowed": edited_floor_allowed,
                                "crate_trained": edited_crate_allowed,
                                "larger_crate_allowed": edited_larger_crate,
                                "crate_size": (
                                    None
                                    if edited_crate_size == "Not set"
                                    else edited_crate_size
                                ),
                                "crate_priority": edited_crate_priority,
                                "kennel_priority": edited_kennel_priority,
                                "suite_priority": edited_suite_priority,
                                "floor_priority": edited_floor_priority,
                                "fence_fighter": edited_fence_fighter,
                                "fence_jumpers": edited_fence_jumper,
                                "Notes": edited_notes,
                                "sibling_group_id": sibling_group_id,
                                "keep_together": edited_keep_together,
                                "shared_suite_priority": (
                                    edited_shared_suite_priority
                                ),
                                "shared_floor_priority": (
                                    edited_shared_floor_priority
                                ),
                                "shared_kennel_priority": (
                                    edited_shared_kennel_priority
                                )
                            }
                        )
                    except (ValueError, TypeError) as error:
                        st.error(str(error))
                    except Exception:
                        st.error(
                            "The dog profile could not be updated. "
                            "Please try again."
                        )
                    else:
                        if updated:
                            for widget_key in sibling_widget_keys:
                                st.session_state.pop(widget_key, None)
                            st.session_state[
                                "dog_management_notice"
                            ] = "Dog profile updated successfully!"
                            st.rerun()
                        else:
                            st.info("No profile changes were detected.")

                if discard_changes:
                    for widget_key in sibling_widget_keys:
                        st.session_state.pop(widget_key, None)
                    st.session_state["dog_management_notice"] = (
                        "Changes discarded. The profile was not updated."
                    )
                    st.rerun()

    st.write("")

    sibling_table_container = st.expander(
        "Sibling Groups",
        expanded=False
    )

    with sibling_table_container:
        st.caption(
            "Sibling priority scale: 0 = Cannot share, "
            "1 = Highest priority, 3 = Lowest priority."
        )

        if sibling_groups_df.empty:
            st.info("No sibling groups have been created yet.")
        else:
            dog_lookup = {
                int(row["dog_id"]): (
                    f'{row["dog_name"]}'
                    + (
                        " (Inactive)"
                        if int(row["active_status"]) == 0
                        else ""
                    )
                )
                for _, row in dogs_df.iterrows()
            }
            sibling_rows = []

            for _, rule in sibling_groups_df.iterrows():
                sibling_names = []

                for field in (
                    "dog1_id",
                    "dog2_id",
                    "dog3_id",
                    "dog4_id"
                ):
                    dog_id = rule[field]

                    if pd.notna(dog_id):
                        dog_id = int(dog_id)
                        sibling_names.append(
                            dog_lookup.get(dog_id, f"Dog ID {dog_id}")
                        )

                sibling_rows.append(
                    {
                        "Group": int(rule["sibling_group_id"]),
                        "Dogs": ", ".join(sibling_names),
                        "Keep Together": yes_or_no(
                            rule["keep_together"]
                        ),
                        "Shared Suite": format_shared_room(
                            rule,
                            "shared_suite_allowed",
                            "shared_suite_priority"
                        ),
                        "Shared Floor": format_shared_room(
                            rule,
                            "shared_floor_allowed",
                            "shared_floor_priority"
                        ),
                        "Shared Kennel": format_shared_room(
                            rule,
                            "shared_kennel_allowed",
                            "shared_kennel_priority"
                        )
                    }
                )

            sibling_table_df = pd.DataFrame(sibling_rows).sort_values(
                by="Group"
            )

            st.dataframe(
                sibling_table_df,
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 + (35 * len(sibling_table_df)))
            )
