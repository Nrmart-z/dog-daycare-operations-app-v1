import base64
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from auth import current_user, has_section


def _go_to(page):
    st.session_state.page = page
    close_id = int(st.session_state.get("mobile_sidebar_close_id", 0)) + 1
    st.session_state["mobile_sidebar_close_id"] = close_id
    st.session_state["close_mobile_sidebar"] = close_id


def _close_mobile_sidebar_after_navigation():
    close_id = st.session_state.pop("close_mobile_sidebar", None)
    if close_id is None:
        return
    components.html(
        f"""
        <script>
        // A unique signal forces this component to execute after every choice.
        const closeSignal = {int(close_id)};
        let attempts = 0;
        const closeMobileSidebar = () => {{
            if (!parent.matchMedia('(max-width: 760px)').matches) return;
            const sidebar = parent.document.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) {{
                if (++attempts < 20) setTimeout(closeMobileSidebar, 40);
                return;
            }}
            const closeButton =
                parent.document.querySelector('[data-testid="stSidebarCollapseButton"] button') ||
                sidebar.querySelector('button[aria-label*="Close sidebar"]') ||
                sidebar.querySelector('button[aria-label*="Collapse sidebar"]') ||
                sidebar.querySelector('button[kind="headerNoPadding"]');
            if (closeButton) {{
                closeButton.click();
            }} else if (++attempts < 20) {{
                setTimeout(closeMobileSidebar, 40);
            }}
        }};
        requestAnimationFrame(closeMobileSidebar);
        </script>
        """,
        height=0,
        width=0,
    )


def show_dashboard_logo():

    logo_path = Path(__file__).resolve().parent.parent / "assets" / "Logo.png"
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    target_label = "Today’s Dogs" if current_user()["role"] == "Crew" else "Dashboard"

    with st.sidebar:
        components.html(
        f"""
        <button id="planet-bark-home" type="button" aria-label="Go to {target_label}">
            <img
                src="data:image/png;base64,{logo_data}"
                alt="Planet Bark"
            >
        </button>
        <style>
            html, body {{ margin: 0; padding: 0; overflow: hidden; background: transparent; }}
            button {{
                display: block; width: 100%; padding: 0; border: 0;
                border-radius: 12px; background: transparent; cursor: pointer;
                transition: background .2s ease, transform .15s ease;
            }}
            button:hover {{ background: #f5f5f5; transform: scale(1.015); }}
            button:focus-visible {{ outline: 3px solid #ed3223; outline-offset: -3px; }}
            img {{ display: block; width: 100%; height: auto; }}
        </style>
        <script>
            document.getElementById("planet-bark-home").addEventListener("click", () => {{
                const target = {target_label!r};
                const buttons = [...window.parent.document.querySelectorAll("button")];
                const navigationButton = buttons.find(
                    button => button.textContent.trim() === target
                );
                if (navigationButton) navigationButton.click();
            }});
        </script>
        """,
        height=105,
        scrolling=False,
        )


def show_sidebar():
    user = current_user()
    if "page" not in st.session_state:
        st.session_state.page = "Overview" if user["role"] == "Crew" else "Dashboard"

    show_dashboard_logo()

    st.sidebar.divider()

    first_name = str(user["display_name"]).strip().split()[0]
    if user["role"] == "Crew":
        st.sidebar.markdown(
            '<span class="crew-sidebar-marker" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
    st.sidebar.markdown(f"**{first_name}**")
    if user["role"] == "Crew":
        if st.sidebar.button("Today’s Dogs", use_container_width=True):
            _go_to("Overview")
        st.sidebar.divider()
        if st.sidebar.button("🚪 Sign Out", type="primary", use_container_width=True):
            st.session_state.clear()
            st.rerun()
        _close_mobile_sidebar_after_navigation()
        return

    if st.sidebar.button("Dashboard", use_container_width=True):
        _go_to("Dashboard")
    if st.sidebar.button("Attendance", use_container_width=True):
        _go_to("Attendance")

    if user["role"] != "Crew":
        if has_section("office") and st.sidebar.button("Assignments", use_container_width=True):
            _go_to("Assignments")
        if st.sidebar.button("Daily Records", use_container_width=True):
            _go_to("Daily Records")

        if has_section("office") and st.sidebar.button("Dog Management", use_container_width=True):
            _go_to("Dog Management")
        if has_section("office") and st.sidebar.button("Room Management", use_container_width=True):
            _go_to("Room Management")
        if has_section("office") and st.sidebar.button("Analytics", use_container_width=True):
            _go_to("Analytics")
        if has_section("manage") and st.sidebar.button("Worker Accounts", use_container_width=True):
            _go_to("Accounts")
        if has_section("developer") and st.sidebar.button("Developer & Audit", use_container_width=True):
            _go_to("Developer")

    if st.sidebar.button("Report a Problem", use_container_width=True):
        if st.session_state.page != "Report a Problem":
            st.session_state["bug_report_source_page"] = (
                st.session_state.page
            )
        _go_to("Report a Problem")

    st.sidebar.divider()

    if st.sidebar.button("🚪 Sign Out", type="primary", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    st.sidebar.divider()

    st.sidebar.success("Database Connected")
    st.sidebar.markdown(
        """
        <div class="sidebar-version-badge">
            <span class="sidebar-version-dot"></span>
            <span class="sidebar-version-copy">
                <small>PLANET BARK</small>
                <strong>Version 1.0.1</strong>
            </span>
            <span class="sidebar-version-current">CURRENT</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    _close_mobile_sidebar_after_navigation()
