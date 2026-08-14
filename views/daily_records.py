import pandas as pd
import streamlit as st

from database import (
    load_assignment_record,
    load_assignment_record_dates,
    load_assignments_by_date
)
from views.assignments import SECTION_ORDER, room_label, room_section, room_sort_key


def highlight_play_group(row):

    play_group = str(row["Play Group"]).strip().lower()

    if play_group == "small":
        background = "background-color: rgba(255, 105, 180, 0.10)"
    elif play_group == "big":
        background = "background-color: rgba(33, 150, 243, 0.10)"
    elif play_group == "separate":
        background = "background-color: rgba(237, 50, 35, 0.20)"
    else:
        background = ""

    return [background] * len(row)


def format_timestamp(value):

    if pd.isna(value):
        return "Not recorded"

    return pd.Timestamp(value).strftime("%m/%d/%Y at %I:%M %p").replace(" at 0", " at ")


def show_daily_records():

    st.title("Daily Records")
    st.caption("Review finalized nap-time assignments by date")

    record_dates = load_assignment_record_dates()

    if not record_dates:
        st.info(
            "No finalized assignment records are available yet. Finalize "
            "a draft on the Assignments page to create the first record."
        )
        return

    st.write("")
    selected_date = st.date_input(
        "Select Assignment Date",
        value=record_dates[0],
        min_value=min(record_dates),
        max_value=max(record_dates),
        format="MM/DD/YYYY",
        key="daily_record_date"
    )
    assignments_df = load_assignments_by_date(selected_date)
    record_df = load_assignment_record(selected_date)

    if assignments_df.empty or record_df.empty:
        st.info("No finalized assignments were saved for that date.")
        return

    record = record_df.iloc[0]
    total_assignments = len(assignments_df)
    boarding_count = int(
        (assignments_df["visit_type"] == "Boarding").sum()
    )
    daycare_count = int(
        (assignments_df["visit_type"] == "Daycare").sum()
    )
    manual_count = int(
        (assignments_df["assignment_type"] == "Manual Override").sum()
    )

    summary_columns = st.columns(5)
    summary_columns[0].metric("Assignments", total_assignments)
    summary_columns[1].metric("Daycare", daycare_count)
    summary_columns[2].metric("Boarding", boarding_count)
    summary_columns[3].metric("Manual Overrides", manual_count)
    summary_columns[4].metric(
        "Revision",
        int(record["revision_number"])
    )

    record_details = st.container(border=True)

    with record_details:
        detail_columns = st.columns(2)
        detail_columns[0].markdown(
            f'**Initially Finalized:** '
            f'{format_timestamp(record["finalized_at"])}'
        )
        detail_columns[1].markdown(
            f'**Last Updated:** {format_timestamp(record["updated_at"])}'
        )

        if pd.notna(record["update_reason"]) and str(
            record["update_reason"]
        ).strip():
            st.markdown(f'**Latest Update Reason:** {record["update_reason"]}')

    st.write("")
    st.subheader("Assignments", anchor=False)

    records = []

    for _, assignment in assignments_df.iterrows():
        assignment_record = assignment.to_dict()
        section = room_section(assignment_record) or "Other"
        records.append(
            {
                "Section": section,
                "sort": room_sort_key(assignment_record),
                "Dog Name": str(assignment["dog_name"]),
                "Visit": str(assignment["visit_type"] or "Not recorded"),
                "Play Group": str(assignment["play_group"] or ""),
                "Room": room_label(assignment_record),
                "Assignment Type": str(assignment["assignment_type"]),
                "Override Reason": (
                    ""
                    if pd.isna(assignment["override_reason"])
                    else str(assignment["override_reason"])
                )
            }
        )

    section_order = [*SECTION_ORDER, "Other"]

    for section in section_order:
        section_rows = [row for row in records if row["Section"] == section]

        if not section_rows:
            continue

        with st.expander(
            f"{section} — {len(section_rows)} dog(s)",
            expanded=section in {"Petite Suites", "Condo Suites"}
        ):
            section_df = pd.DataFrame(
                sorted(section_rows, key=lambda row: row["sort"])
            ).drop(columns=["Section", "sort"])
            st.dataframe(
                section_df.style.apply(highlight_play_group, axis=1),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 + (35 * len(section_df)))
            )
