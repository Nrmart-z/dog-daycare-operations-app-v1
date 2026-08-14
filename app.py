import streamlit as st

from auth import change_password, current_user, has_section, show_login_gate, uses_password
from components.sidebar import show_sidebar

from views.dashboard import show_dashboard
from views.attendance import show_attendance, show_crew_attendance
from views.assignments import show_assignments
from views.daily_records import show_daily_records
from views.dog_management import show_crew_dog_records, show_dog_management
from views.room_management import show_room_management
from views.analytics import show_analytics
from views.bug_reports import show_bug_reports
from views.boarding_care import show_boarding_care
from views.staff_operations import (
    show_accounts, show_audit, show_overview,
    show_schedule, show_task_management, show_time_off,
)


# =============================================
# Page Configuration
# =============================================

st.set_page_config(
    page_title="Planet Bark - Nap Time Assignment System",
    layout="wide",
    initial_sidebar_state="auto"
)


# =============================================
# Load CSS
# =============================================

def load_css():
    with open("assets/styles.css", "r") as css:
        st.markdown(
            f"<style>{css.read()}</style>",
            unsafe_allow_html=True
        )


load_css()

if not show_login_gate():
    st.stop()

if current_user().get("must_change_password"):
    credential_name = "password" if uses_password(current_user()["role"]) else "PIN"
    st.title(f"Create your new {credential_name}")
    st.info(f"Your temporary {credential_name} must be replaced before using the app.")
    with st.form("required_password_change"):
        new_password = st.text_input(f"New {credential_name}", type="password")
        confirm_password = st.text_input(f"Confirm {credential_name}", type="password")
        submitted = st.form_submit_button(f"Save new {credential_name}", use_container_width=True)
    if submitted:
        if new_password != confirm_password:
            st.error(f"{credential_name.title()} entries do not match.")
        else:
            try:
                change_password(current_user()["user_id"], new_password)
                st.session_state.current_user["must_change_password"] = 0
                st.success(f"{credential_name.title()} changed."); st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()


# =============================================
# Sidebar
# =============================================


show_sidebar()



# =============================================
# Page Navigation
# =============================================
if "page" not in st.session_state:
    st.session_state.page = "Overview"

page = st.session_state.page

# Crew and Office previously pointed to standalone task lists. Keep old browser
# sessions and bookmarks from landing on retired pages.
if page in {"Crew", "Office"}:
    page = "Overview"
    st.session_state.page = page

retired_workflow_pages = {"Schedule", "Time Off", "Task Management", "Boarding Care"}
if page in retired_workflow_pages:
    page = "Overview" if current_user()["role"] == "Crew" else "Dashboard"
    st.session_state.page = page

if current_user()["role"] != "Crew" and page == "Overview":
    page = "Dashboard"
    st.session_state.page = page

crew_pages = {"Overview"}
if current_user()["role"] == "Crew" and page not in crew_pages:
    page = "Overview"
    st.session_state.page = page

office_only_pages = {"Assignments", "Dog Management", "Room Management", "Analytics"}
if page in office_only_pages and not has_section("office"):
    st.error("Your account does not have access to this page.")
    st.stop()

if page == "Overview":
    show_overview()
elif page == "Task Management":
    show_task_management()
elif page == "Schedule":
    show_schedule()
elif page == "Time Off":
    show_time_off()
elif page == "Accounts":
    show_accounts()
elif page == "Developer":
    show_audit()
elif page == "Dashboard":
    show_dashboard()

elif page == "Attendance":
    if current_user()["role"] == "Crew":
        show_crew_attendance()
    else:
        show_attendance()

elif page == "Assignments":
    show_assignments()

elif page == "Daily Records":
    show_daily_records()

elif page == "Boarding Care":
    show_boarding_care()

elif page == "Dog Management":
    show_dog_management()

elif page == "Dog Records":
    if current_user()["role"] == "Crew":
        show_crew_dog_records()
    else:
        show_dog_management()

elif page == "Room Management":
    show_room_management()

elif page == "Analytics":
    show_analytics()

elif page == "Report a Problem":
    show_bug_reports()
