from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database import (
    load_analytics_data,
    load_assignment_record_dates
)


WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]


def season_name(month):

    if month in {12, 1, 2}:
        return "Winter"
    if month in {3, 4, 5}:
        return "Spring"
    if month in {6, 7, 8}:
        return "Summer"
    return "Fall"


def analytics_room_area(room):

    room_type = str(room.get("room_type") or "").strip().lower()
    room_number = str(room.get("room_number") or "").strip()

    try:
        numeric_room = int(float(room_number))
    except (TypeError, ValueError):
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
        if 42 <= numeric_room <= 53:
            return "Kennels"
        if 54 <= numeric_room <= 58:
            return "Front Kennel"
        if numeric_room in {59, 60}:
            return "Crate Room"
        if numeric_room in {27, 28, 29, 34, 36, 38}:
            return "Back Hall"
    return "Other"


def format_date(value):

    if value is None or pd.isna(value):
        return "No recorded visit"

    return pd.Timestamp(value).strftime("%m/%d/%Y")


def boarding_nights(stays_df):

    if stays_df.empty:
        return pd.Series(dtype="int64")

    check_in = pd.to_datetime(stays_df["check_in_datetime"])
    checkout = pd.to_datetime(
        stays_df["actual_checkout_datetime"]
    ).fillna(pd.to_datetime(stays_df["planned_checkout_datetime"]))

    return (
        checkout.dt.normalize() - check_in.dt.normalize()
    ).dt.days.clip(lower=1)


def build_daily_summary(records_df, attendance_df):

    daily = records_df[["record_date"]].drop_duplicates().rename(
        columns={"record_date": "Date"}
    )
    daily["Date"] = pd.to_datetime(daily["Date"])

    if attendance_df.empty:
        daily["Total Dogs"] = 0
        daily["Daycare"] = 0
        daily["Boarding"] = 0
        daily["Separate"] = 0
    else:
        visits = attendance_df.copy()
        visits["attendance_date"] = pd.to_datetime(
            visits["attendance_date"]
        )
        visits = visits.drop_duplicates(
            subset=["attendance_date", "dog_id"]
        )

        def daily_counts(frame, column_name):
            return (
                frame.groupby("attendance_date")["dog_id"]
                .nunique()
                .rename(column_name)
            )

        totals = daily_counts(visits, "Total Dogs")
        daycare = daily_counts(
            visits[visits["visit_type"] == "Daycare"],
            "Daycare"
        )
        boarding = daily_counts(
            visits[visits["visit_type"] == "Boarding"],
            "Boarding"
        )
        separate = daily_counts(
            visits[visits["play_group"] == "Separate"],
            "Separate"
        )
        daily = daily.set_index("Date").join(
            [totals, daycare, boarding, separate]
        ).fillna(0).reset_index()

    count_columns = ["Total Dogs", "Daycare", "Boarding", "Separate"]
    daily[count_columns] = daily[count_columns].astype(int)
    daily["Weekday"] = daily["Date"].dt.day_name()
    daily["Month"] = daily["Date"].dt.to_period("M").astype(str)
    daily["Season"] = daily["Date"].dt.month.map(season_name)
    return daily.sort_values("Date")


def show_overview(daily_df):

    st.subheader("Weekday Averages", anchor=False)
    weekday_data = daily_df[daily_df["Weekday"].isin(WEEKDAY_ORDER)]
    weekday_summary = (
        weekday_data.groupby("Weekday")
        .agg(
            **{
                "Average Dogs": ("Total Dogs", "mean"),
                "Average Daycare": ("Daycare", "mean"),
                "Average Boarding": ("Boarding", "mean"),
                "Recorded Days": ("Date", "count")
            }
        )
        .reindex(WEEKDAY_ORDER)
        .dropna(how="all")
        .reset_index()
    )

    if weekday_summary.empty:
        st.info("No Monday–Friday finalized records are in this period.")
    else:
        weekday_summary[[
            "Average Dogs", "Average Daycare", "Average Boarding"
        ]] = weekday_summary[[
            "Average Dogs", "Average Daycare", "Average Boarding"
        ]].round(1)
        st.bar_chart(
            weekday_summary.set_index("Weekday")[[
                "Average Daycare", "Average Boarding"
            ]]
        )
        st.dataframe(
            weekday_summary,
            use_container_width=True,
            hide_index=True
        )

    chart_left, chart_right = st.columns(2)

    with chart_left:
        st.subheader("Monthly Average", anchor=False)
        monthly = (
            daily_df.groupby("Month")
            .agg(
                **{
                    "Average Dogs": ("Total Dogs", "mean"),
                    "Recorded Days": ("Date", "count")
                }
            )
            .round(1)
        )
        st.line_chart(monthly[["Average Dogs"]])
        st.dataframe(
            monthly.reset_index(),
            use_container_width=True,
            hide_index=True
        )

    with chart_right:
        st.subheader("Seasonal Average", anchor=False)
        seasonal = (
            daily_df.groupby("Season")
            .agg(
                **{
                    "Average Dogs": ("Total Dogs", "mean"),
                    "Recorded Days": ("Date", "count")
                }
            )
            .reindex(SEASON_ORDER)
            .dropna(how="all")
            .round(1)
        )
        st.bar_chart(seasonal[["Average Dogs"]])
        st.dataframe(
            seasonal.reset_index(),
            use_container_width=True,
            hide_index=True
        )
        if not seasonal.empty and seasonal["Recorded Days"].max() < 20:
            st.caption(
                "Seasonal results are preliminary; they become more useful "
                "after more finalized days are recorded."
            )

    st.subheader("Busiest Recorded Days", anchor=False)
    busiest = daily_df.nlargest(10, "Total Dogs")[
        ["Date", "Weekday", "Total Dogs", "Daycare", "Boarding", "Separate"]
    ].copy()
    busiest["Date"] = busiest["Date"].dt.strftime("%m/%d/%Y")
    st.dataframe(busiest, use_container_width=True, hide_index=True)


def leaderboard(frame, count_name, date_column=None):

    if frame.empty:
        return pd.DataFrame(columns=["Dog Name", count_name])

    if date_column:
        result = (
            frame.groupby(["dog_id", "dog_name"])[date_column]
            .nunique()
            .rename(count_name)
            .reset_index()
        )
    else:
        result = (
            frame.groupby(["dog_id", "dog_name"])
            .size()
            .rename(count_name)
            .reset_index()
        )

    return result.sort_values(
        [count_name, "dog_name"],
        ascending=[False, True]
    ).head(10).rename(columns={"dog_name": "Dog Name"})[
        ["Dog Name", count_name]
    ]


def show_dog_insights(data, assignments_df):

    dogs_df = data["dogs"].copy()
    all_visits_df = data["all_visits"].copy()
    all_stays_df = data["all_boarding_stays"].copy()

    st.subheader("Dog Visit History", anchor=False)
    search = st.text_input(
        "Search Dog",
        placeholder="Search by name or nickname...",
        key="analytics_dog_search"
    )
    matching_dogs = dogs_df.copy()

    if search:
        matching_dogs = matching_dogs[
            matching_dogs["dog_name"].str.contains(
                search, case=False, na=False
            )
            | matching_dogs["dog_nickname"].fillna("").str.contains(
                search, case=False, na=False
            )
        ]

    dog_options = {None: "Select a dog..."}
    dog_options.update(
        {
            int(row["dog_id"]): (
                str(row["dog_name"])
                + (
                    f' · {row["dog_nickname"]}'
                    if pd.notna(row["dog_nickname"])
                    and str(row["dog_nickname"]).strip()
                    else ""
                )
            )
            for _, row in matching_dogs.iterrows()
        }
    )
    selected_dog_id = st.selectbox(
        "Dog",
        options=list(dog_options),
        format_func=dog_options.get,
        key="analytics_selected_dog"
    )

    if selected_dog_id is not None:
        selected_dog = dogs_df[
            dogs_df["dog_id"].astype(int) == int(selected_dog_id)
        ].iloc[0]
        dog_visits = all_visits_df[
            all_visits_df["dog_id"].astype(int) == int(selected_dog_id)
        ].copy()
        dog_daycare = dog_visits[dog_visits["visit_type"] == "Daycare"]
        dog_boarding_visits = dog_visits[
            dog_visits["visit_type"] == "Boarding"
        ]
        dog_stays = all_stays_df[
            all_stays_df["dog_id"].astype(int) == int(selected_dog_id)
        ].copy()
        dog_stays["boarding_nights"] = boarding_nights(dog_stays)
        metrics = st.columns(5)
        metrics[0].metric(
            "Daycare Visits",
            dog_daycare["attendance_date"].nunique()
        )
        metrics[1].metric("Boarding Stays", len(dog_stays))
        metrics[2].metric(
            "Boarding Nights",
            int(dog_stays["boarding_nights"].sum())
            if not dog_stays.empty else 0
        )
        metrics[3].metric(
            "Last Daycare Visit",
            format_date(dog_daycare["attendance_date"].max())
        )
        metrics[4].metric(
            "Last Boarding Date",
            format_date(
                dog_stays["check_in_datetime"].max()
                if not dog_stays.empty
                else dog_boarding_visits["attendance_date"].max()
            )
        )
        st.caption(
            f'Play group: {selected_dog["play_group"]} · Profile: '
            + (
                "Active"
                if int(selected_dog["active_status"]) == 1
                else "Inactive"
            )
        )

        dog_assignments = assignments_df[
            assignments_df["dog_id"].astype(int) == int(selected_dog_id)
        ]
        if not dog_assignments.empty:
            favorite_room = (
                dog_assignments.assign(
                    Room=dog_assignments["room_name"].fillna("").where(
                        dog_assignments["room_name"].fillna("").ne(""),
                        dog_assignments["room_number"].astype(str)
                    )
                )["Room"].value_counts().index[0]
            )
            st.info(
                f"Most-used nap room in this reporting period: "
                f"{favorite_room}"
            )

    st.divider()
    attendance_df = data["attendance"]
    daycare = attendance_df[attendance_df["visit_type"] == "Daycare"]
    stays = data["boarding_stays"].copy()
    stays["Boarding Nights"] = boarding_nights(stays)

    leader_columns = st.columns(3)
    with leader_columns[0]:
        st.subheader("Top Daycare Dogs", anchor=False)
        st.dataframe(
            leaderboard(daycare, "Visits", "attendance_date"),
            use_container_width=True,
            hide_index=True
        )
    with leader_columns[1]:
        st.subheader("Most Boarding Stays", anchor=False)
        st.dataframe(
            leaderboard(stays, "Stays"),
            use_container_width=True,
            hide_index=True
        )
    with leader_columns[2]:
        st.subheader("Most Boarding Nights", anchor=False)
        if stays.empty:
            nights_leaderboard = pd.DataFrame(
                columns=["Dog Name", "Nights"]
            )
        else:
            nights_leaderboard = (
                stays.groupby(["dog_id", "dog_name"])["Boarding Nights"]
                .sum()
                .rename("Nights")
                .reset_index()
                .sort_values(
                    ["Nights", "dog_name"],
                    ascending=[False, True]
                )
                .head(10)
                .rename(columns={"dog_name": "Dog Name"})[
                    ["Dog Name", "Nights"]
                ]
            )
        st.dataframe(
            nights_leaderboard,
            use_container_width=True,
            hide_index=True
        )


def show_room_and_boarding(data, daily_df):

    assignments_df = data["assignments"].copy()
    stays_df = data["boarding_stays"].copy()
    stays_df["Boarding Nights"] = boarding_nights(stays_df)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Boarding Stays", len(stays_df))
    metric_columns[1].metric(
        "Boarding Nights",
        int(stays_df["Boarding Nights"].sum()) if not stays_df.empty else 0
    )
    metric_columns[2].metric(
        "Average Stay",
        (
            f'{stays_df["Boarding Nights"].mean():.1f} nights'
            if not stays_df.empty else "0 nights"
        )
    )
    metric_columns[3].metric(
        "Average Boarders/Day",
        f'{daily_df["Boarding"].mean():.1f}'
    )

    if assignments_df.empty:
        st.info("No finalized assignment rooms exist in this period.")
        return

    assignments_df["Area"] = assignments_df.apply(
        analytics_room_area, axis=1
    )
    room_use = (
        assignments_df.groupby(["room_id", "room_number", "room_name"])
        .agg(
            Assignments=("dog_id", "count"),
            Days_Used=("assignment_date", "nunique")
        )
        .reset_index()
        .sort_values(["Assignments", "room_id"], ascending=[False, True])
        .head(15)
        .rename(columns={"Days_Used": "Days Used"})
    )
    room_use["Room"] = room_use["room_name"].fillna("").where(
        room_use["room_name"].fillna("").ne(""),
        room_use["room_number"].astype(str)
    )
    area_use = (
        assignments_df.groupby("Area")
        .agg(
            Assignments=("dog_id", "count"),
            Days_Used=("assignment_date", "nunique")
        )
        .rename(columns={"Days_Used": "Days Used"})
        .sort_values("Assignments", ascending=False)
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Room-Area Demand", anchor=False)
        st.bar_chart(area_use[["Assignments"]])
        st.dataframe(
            area_use.reset_index(),
            use_container_width=True,
            hide_index=True
        )
    with right:
        st.subheader("Most-Used Rooms", anchor=False)
        st.dataframe(
            room_use[["Room", "Assignments", "Days Used"]],
            use_container_width=True,
            hide_index=True
        )

    play_group_demand = (
        assignments_df.groupby("play_group")["dog_id"]
        .count()
        .rename("Assignments")
        .sort_values(ascending=False)
    )
    st.subheader("Play-Group Demand", anchor=False)
    st.bar_chart(play_group_demand)


def show_assignment_quality(data):

    assignments_df = data["assignments"].copy()
    records_df = data["records"].copy()

    if assignments_df.empty:
        st.info("No finalized assignments exist in this period.")
        return

    manual_mask = assignments_df["assignment_type"].str.startswith(
        "Manual", na=False
    )
    manual_count = int(manual_mask.sum())
    automatic_count = len(assignments_df) - manual_count
    override_count = int(
        (assignments_df["assignment_type"] == "Manual Override").sum()
    )
    revision_count = int(
        (records_df["revision_number"].fillna(1).astype(int) - 1)
        .clip(lower=0)
        .sum()
    )
    metrics = st.columns(4)
    metrics[0].metric("Automatic Assignments", automatic_count)
    metrics[1].metric("Manual Moves", manual_count)
    metrics[2].metric(
        "Manual Rate",
        f"{(manual_count / len(assignments_df)) * 100:.1f}%"
    )
    metrics[3].metric("Saved Revisions", revision_count)

    left, right = st.columns(2)
    with left:
        st.subheader("Assignment Types", anchor=False)
        assignment_types = assignments_df["assignment_type"].value_counts()
        st.bar_chart(assignment_types)
        st.dataframe(
            assignment_types.rename("Count").reset_index().rename(
                columns={"assignment_type": "Assignment Type"}
            ),
            use_container_width=True,
            hide_index=True
        )
    with right:
        st.subheader("Override Reasons", anchor=False)
        reasons = assignments_df.loc[
            assignments_df["override_reason"].notna()
            & assignments_df["override_reason"].astype(str).str.strip().ne(""),
            "override_reason"
        ].value_counts()

        if reasons.empty:
            st.success("No manual override reasons in this period.")
        else:
            st.dataframe(
                reasons.rename("Count").reset_index().rename(
                    columns={"override_reason": "Reason"}
                ),
                use_container_width=True,
                hide_index=True
            )

    if override_count:
        frequent_override_dogs = (
            assignments_df[manual_mask]
            .groupby("dog_name")
            .size()
            .rename("Manual Placements")
            .sort_values(ascending=False)
            .head(10)
            .reset_index()
            .rename(columns={"dog_name": "Dog Name"})
        )
        st.subheader("Dogs with the Most Manual Placements", anchor=False)
        st.dataframe(
            frequent_override_dogs,
            use_container_width=True,
            hide_index=True
        )


def show_analytics():

    st.title("Analytics")
    st.caption("Attendance, boarding, room demand, and assignment insights")
    record_dates = load_assignment_record_dates()

    if not record_dates:
        st.info(
            "Analytics will appear after the first daily assignment record "
            "is finalized."
        )
        return

    earliest_date = min(record_dates)
    latest_date = max(record_dates)
    today = date.today()
    preset = st.selectbox(
        "Reporting Period",
        ["This Month", "Last 30 Days", "Last 90 Days", "This Year", "All Records", "Custom"]
    )

    if preset == "This Month":
        start_date = max(earliest_date, today.replace(day=1))
        end_date = latest_date
    elif preset == "Last 30 Days":
        start_date = max(earliest_date, latest_date - timedelta(days=29))
        end_date = latest_date
    elif preset == "Last 90 Days":
        start_date = max(earliest_date, latest_date - timedelta(days=89))
        end_date = latest_date
    elif preset == "This Year":
        start_date = max(earliest_date, date(today.year, 1, 1))
        end_date = latest_date
    elif preset == "All Records":
        start_date = earliest_date
        end_date = latest_date
    else:
        selected_range = st.date_input(
            "Custom Date Range",
            value=(earliest_date, latest_date),
            min_value=earliest_date,
            max_value=latest_date,
            format="MM/DD/YYYY"
        )
        if len(selected_range) != 2:
            st.info("Select both a start date and an end date.")
            return
        start_date, end_date = selected_range

    if start_date > end_date:
        start_date = earliest_date

    data = load_analytics_data(start_date, end_date)
    records_df = data["records"].copy()

    if records_df.empty:
        st.info("No finalized Daily Records exist in this reporting period.")
        return

    daily_df = build_daily_summary(records_df, data["attendance"])
    busiest_row = daily_df.loc[daily_df["Total Dogs"].idxmax()]
    metrics = st.columns(5)
    metrics[0].metric("Finalized Days", len(daily_df))
    metrics[1].metric("Average Dogs", f'{daily_df["Total Dogs"].mean():.1f}')
    metrics[2].metric("Average Daycare", f'{daily_df["Daycare"].mean():.1f}')
    metrics[3].metric("Average Boarding", f'{daily_df["Boarding"].mean():.1f}')
    metrics[4].metric(
        "Busiest Day",
        int(busiest_row["Total Dogs"]),
        delta=busiest_row["Date"].strftime("%m/%d/%Y"),
        delta_color="off"
    )
    st.caption(
        f"Reporting on {len(daily_df)} finalized day(s) from "
        f"{start_date:%m/%d/%Y} through {end_date:%m/%d/%Y}."
    )

    overview_tab, dogs_tab, rooms_tab, quality_tab = st.tabs(
        ["Overview", "Dogs", "Boarding & Rooms", "Assignment Quality"]
    )
    with overview_tab:
        show_overview(daily_df)
    with dogs_tab:
        show_dog_insights(data, data["assignments"])
    with rooms_tab:
        show_room_and_boarding(data, daily_df)
    with quality_tab:
        show_assignment_quality(data)
