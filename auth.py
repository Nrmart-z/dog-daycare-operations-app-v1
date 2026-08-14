import base64
import hashlib
import hmac
import os

import streamlit as st

from database import connect_database


ROLES = ("Developer", "Boss", "Cross-Trained", "Office", "Crew")
ROLE_SECTIONS = {
    "Developer": {"overview", "crew", "office", "manage", "developer"},
    "Boss": {"overview", "crew", "office", "manage"},
    "Cross-Trained": {"overview", "crew", "office"},
    "Office": {"overview", "office"},
    "Crew": {"overview", "crew"},
}


def uses_password(role):
    return role in ("Developer", "Boss")


def validate_credential(credential, role):
    if uses_password(role):
        if len(credential) < 10:
            raise ValueError("Management passwords must be at least 10 characters.")
    elif not credential.isdigit() or len(credential) != 3:
        raise ValueError("Worker PINs must contain exactly 3 numbers.")


def hash_password(password, iterations=260000):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def has_section(section):
    user = st.session_state.get("current_user") or {}
    return section in ROLE_SECTIONS.get(user.get("role"), set())


def current_user():
    return st.session_state.get("current_user")


def user_count():
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM staff_users")
        return int(cursor.fetchone()[0])
    finally:
        cursor.close(); connection.close()


def create_user(username, first_name, last_name, password, role, actor_id=None, must_change=True):
    username = username.strip().lower()
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not first_name or not last_name:
        raise ValueError("First name and last name are required.")
    display_name = f"{first_name} {last_name}"
    if role not in ROLES:
        raise ValueError("Invalid role.")
    if len(username) < 3:
        raise ValueError("Usernames must contain at least 3 characters.")
    validate_credential(password, role)
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO staff_users
               (username, first_name, last_name, display_name, password_hash, role, must_change_password)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (username, first_name, last_name, display_name, hash_password(password), role, int(must_change))
        )
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO notification_preferences (user_id) VALUES (%s)", (user_id,)
        )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'CREATE','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Created {display_name} as {role}")
        )
        connection.commit(); return user_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def authenticate(username, password):
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT user_id, username, first_name, last_name, display_name, password_hash, role,
                      must_change_password FROM staff_users
               WHERE username=%s AND active=1""", (username.strip().lower(),)
        )
        row = cursor.fetchone()
        if not row or not verify_password(password, row.pop("password_hash")):
            return None
        cursor.execute("UPDATE staff_users SET last_login_at=NOW() WHERE user_id=%s", (row["user_id"],))
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'LOGIN','session',%s,'Successful login')""",
            (row["user_id"], str(row["user_id"]))
        )
        connection.commit(); return row
    finally:
        cursor.close(); connection.close()


def change_password(user_id, password):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute("SELECT role FROM staff_users WHERE user_id=%s", (int(user_id),))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Account not found.")
        validate_credential(password, row[0])
        cursor.execute(
            "UPDATE staff_users SET password_hash=%s, must_change_password=0 WHERE user_id=%s",
            (hash_password(password), int(user_id))
        )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'PASSWORD_CHANGE','staff_user',%s,'Password changed')""",
            (int(user_id), str(user_id))
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def show_login_gate():
    if current_user():
        return True
    st.title("Planet Bark Staff")
    st.caption("Secure staff operations")
    try:
        first_run = user_count() == 0
    except Exception:
        st.error("Staff tables are not ready. Run migration 012_staff_operations.sql.")
        st.stop()
    if first_run:
        st.info("Create the first system-owner account. This setup is available only while no accounts exist.")
        with st.form("developer_setup"):
            first_name = st.text_input("First name")
            last_name = st.text_input("Last name")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create system-owner account", use_container_width=True)
        if submitted:
            if password != confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    create_user(username, first_name, last_name, password, "Developer", must_change=False)
                    st.success("System-owner account created. Sign in below."); st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        return False
    with st.form("staff_login"):
        username = st.text_input("Username")
        password = st.text_input("PIN or password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
    if submitted:
        user = authenticate(username, password)
        if user:
            st.session_state.current_user = user
            st.session_state.page = "Overview"
            st.rerun()
        st.error("Username, PIN, or password is incorrect.")
    return False
