import pandas as pd
import streamlit as st

from database import (
    create_bug_report,
    load_bug_reports,
    update_bug_report
)
from email_notifications import (
    DEFAULT_REPORT_RECIPIENT,
    report_email_is_configured,
    send_bug_report_email
)


PAGE_OPTIONS = [
    "Dashboard",
    "Attendance",
    "Assignments",
    "Daily Records",
    "Dog Management",
    "Room Management",
    "Analytics",
    "Sidebar / Navigation",
    "Database / Data",
    "Other"
]
STATUS_OPTIONS = ["New", "Reviewing", "In Progress", "Fixed", "Closed"]


def status_badge_class(status):

    return {
        "New": "status-badge--red",
        "Reviewing": "status-badge--yellow",
        "In Progress": "status-badge--blue",
        "Fixed": "status-badge--green",
        "Closed": "status-badge--green"
    }.get(str(status), "status-badge--yellow")


def get_email_settings():

    try:
        return st.secrets.get("email", {})
    except Exception:
        return {}


def show_bug_reports():

    st.title("Report a Problem")
    st.caption("Record bugs, data concerns, rule issues, and update ideas")
    notice = st.session_state.pop("bug_report_notice", None)

    if notice:
        st.success(notice)

    source_page = st.session_state.get(
        "bug_report_source_page", "Other"
    )
    default_page = (
        source_page if source_page in PAGE_OPTIONS else "Other"
    )
    report_tab, tracker_tab = st.tabs(
        ["Submit Report", "Issue Tracker"]
    )

    with report_tab:
        email_settings = get_email_settings()
        email_ready = report_email_is_configured(email_settings)
        st.caption(
            "Please include enough detail for someone to reproduce the "
            "problem during the next update."
        )
        if email_ready:
            st.caption(
                f"A notification will also be emailed to "
                f"{DEFAULT_REPORT_RECIPIENT}."
            )
        else:
            st.info(
                f"Reports are saved in the Issue Tracker. Email alerts to "
                f"{DEFAULT_REPORT_RECIPIENT} are ready to enable once "
                "approved sender access is provided."
            )

        with st.form("submit_bug_report_form", clear_on_submit=True):
            first_row = st.columns(3)
            report_type = first_row[0].selectbox(
                "Report Type",
                [
                    "Bug",
                    "Feature Request",
                    "Data Issue",
                    "Assignment Rule Issue"
                ]
            )
            priority = first_row[1].selectbox(
                "Priority",
                ["Medium", "Low", "High", "Urgent"]
            )
            page_name = first_row[2].selectbox(
                "Page",
                PAGE_OPTIONS,
                index=PAGE_OPTIONS.index(default_page)
            )
            title = st.text_input(
                "Short Title *",
                max_chars=100,
                placeholder="Example: Room 54 disappeared after moving a dog"
            )
            description = st.text_area(
                "What happened or what should be added? *",
                max_chars=2000,
                height=130
            )
            behavior_columns = st.columns(2)
            expected_behavior = behavior_columns[0].text_area(
                "What did you expect?",
                max_chars=1000,
                height=110
            )
            actual_behavior = behavior_columns[1].text_area(
                "What actually happened?",
                max_chars=1000,
                height=110
            )
            related_columns = st.columns(3)
            related_dog = related_columns[0].text_input(
                "Dog Involved",
                max_chars=100
            )
            related_room = related_columns[1].text_input(
                "Room Involved",
                max_chars=50
            )
            reporter_name = related_columns[2].text_input(
                "Employee Name",
                max_chars=100
            )
            confirm_report = st.checkbox(
                "I reviewed this report and included the important details"
            )
            submit_report = st.form_submit_button(
                "Submit Report",
                type="primary",
                use_container_width=True
            )

            if submit_report:
                if not confirm_report:
                    st.warning("Confirm the report before submitting it.")
                else:
                    report_data = {
                        "report_type": report_type,
                        "page_name": page_name,
                        "priority": priority,
                        "title": title,
                        "description": description,
                        "expected_behavior": expected_behavior,
                        "actual_behavior": actual_behavior,
                        "related_dog": related_dog,
                        "related_room": related_room,
                        "reporter_name": reporter_name,
                        "app_version": "1.0.1"
                    }
                    try:
                        report_id = create_bug_report(report_data)
                    except (ValueError, TypeError) as error:
                        st.error(str(error))
                    except Exception:
                        st.error(
                            "The report could not be saved. Please try again."
                        )
                    else:
                        email_sent = False
                        if email_ready:
                            try:
                                email_sent = send_bug_report_email(
                                    report_id,
                                    report_data,
                                    email_settings
                                )
                            except Exception:
                                email_sent = False

                        notice = (
                            f"Report #{report_id} was submitted successfully."
                        )
                        if email_sent:
                            notice += (
                                f" An email was sent to "
                                f"{DEFAULT_REPORT_RECIPIENT}."
                            )
                        elif email_ready:
                            notice += (
                                " The email notification could not be sent, "
                                "but the report is safely stored in the "
                                "Issue Tracker."
                            )
                        st.session_state["bug_report_notice"] = notice
                        st.rerun()

    with tracker_tab:
        reports_df = load_bug_reports()

        if reports_df.empty:
            st.info("No problems or update requests have been reported yet.")
            return

        open_mask = ~reports_df["report_status"].isin(["Fixed", "Closed"])
        metric_columns = st.columns(4)
        metric_columns[0].metric("Open Reports", int(open_mask.sum()))
        metric_columns[1].metric(
            "Urgent / High",
            int(
                (
                    open_mask
                    & reports_df["priority"].isin(["Urgent", "High"])
                ).sum()
            )
        )
        metric_columns[2].metric(
            "In Progress",
            int((reports_df["report_status"] == "In Progress").sum())
        )
        metric_columns[3].metric(
            "Fixed",
            int((reports_df["report_status"] == "Fixed").sum())
        )

        filters = st.columns(3)
        status_filter = filters[0].selectbox(
            "Status",
            ["Open", "All", *STATUS_OPTIONS],
            key="bug_tracker_status_filter"
        )
        type_filter = filters[1].selectbox(
            "Type",
            ["All", "Bug", "Feature Request", "Data Issue", "Assignment Rule Issue"],
            key="bug_tracker_type_filter"
        )
        search = filters[2].text_input(
            "Search Reports",
            placeholder="Title, dog, room, or description...",
            key="bug_tracker_search"
        )
        filtered_reports = reports_df.copy()

        if status_filter == "Open":
            filtered_reports = filtered_reports[
                ~filtered_reports["report_status"].isin(["Fixed", "Closed"])
            ]
        elif status_filter != "All":
            filtered_reports = filtered_reports[
                filtered_reports["report_status"] == status_filter
            ]

        if type_filter != "All":
            filtered_reports = filtered_reports[
                filtered_reports["report_type"] == type_filter
            ]

        if search:
            search_columns = [
                "title", "description", "related_dog", "related_room"
            ]
            search_mask = pd.Series(False, index=filtered_reports.index)

            for column in search_columns:
                search_mask |= filtered_reports[column].fillna("").str.contains(
                    search, case=False, na=False
                )

            filtered_reports = filtered_reports[search_mask]

        display_df = filtered_reports[
            [
                "report_id",
                "priority",
                "report_status",
                "report_type",
                "page_name",
                "title",
                "related_dog",
                "related_room",
                "created_at"
            ]
        ].rename(
            columns={
                "report_id": "ID",
                "priority": "Priority",
                "report_status": "Status",
                "report_type": "Type",
                "page_name": "Page",
                "title": "Title",
                "related_dog": "Dog",
                "related_room": "Room",
                "created_at": "Reported"
            }
        )
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=min(420, 38 + (35 * max(len(display_df), 1)))
        )

        if filtered_reports.empty:
            st.info("No reports matched those filters.")
            return

        report_options = {
            int(row["report_id"]): (
                f'#{int(row["report_id"])} · {row["title"]}'
            )
            for _, row in filtered_reports.iterrows()
        }
        selected_report_id = st.selectbox(
            "Review Report",
            options=list(report_options),
            format_func=report_options.get,
            key="bug_tracker_selected_report"
        )
        selected_report = filtered_reports[
            filtered_reports["report_id"].astype(int)
            == selected_report_id
        ].iloc[0]

        with st.expander("Report Details", expanded=True):
            st.markdown(
                f'<span class="status-badge '
                f'{status_badge_class(selected_report["report_status"])}">'
                f'{selected_report["report_status"]}</span>',
                unsafe_allow_html=True
            )
            st.markdown(f'### #{selected_report_id} — {selected_report["title"]}')
            st.write(selected_report["description"])
            detail_columns = st.columns(2)
            detail_columns[0].markdown(
                "**Expected:** "
                + (
                    "Not provided"
                    if pd.isna(selected_report["expected_behavior"])
                    else str(selected_report["expected_behavior"])
                )
            )
            detail_columns[1].markdown(
                "**Actual:** "
                + (
                    "Not provided"
                    if pd.isna(selected_report["actual_behavior"])
                    else str(selected_report["actual_behavior"])
                )
            )
            st.caption(
                f'Page: {selected_report["page_name"]} · '
                f'Version: {selected_report["app_version"]} · '
                "Reporter: "
                + (
                    "Not provided"
                    if pd.isna(selected_report["reporter_name"])
                    else str(selected_report["reporter_name"])
                )
            )

            with st.form(f"update_bug_report_{selected_report_id}"):
                current_status = str(selected_report["report_status"])
                updated_status = st.selectbox(
                    "Status",
                    STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(current_status)
                )
                resolution_notes = st.text_area(
                    "Resolution / Update Notes",
                    value=(
                        ""
                        if pd.isna(selected_report["resolution_notes"])
                        else str(selected_report["resolution_notes"])
                    ),
                    max_chars=2000
                )
                confirm_update = st.checkbox(
                    "Confirm this issue-tracker update"
                )
                save_update = st.form_submit_button(
                    "Update Report",
                    type="primary",
                    use_container_width=True
                )

                if save_update:
                    if not confirm_update:
                        st.warning("Confirm the update before saving it.")
                    else:
                        try:
                            updated = update_bug_report(
                                selected_report_id,
                                updated_status,
                                resolution_notes
                            )
                        except (ValueError, TypeError) as error:
                            st.error(str(error))
                        except Exception:
                            st.error("The report could not be updated.")
                        else:
                            if updated:
                                st.session_state["bug_report_notice"] = (
                                    f"Report #{selected_report_id} was updated."
                                )
                                st.rerun()
