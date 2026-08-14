from pathlib import Path
import py_compile

from auth import hash_password, validate_credential, verify_password
from database import connect_database, load_todays_boarding_movements
from operations_service import load_day_summary
from views.boarding_care import _can_edit_boarding, _has_boarding_sibling, _meal_roster
from views.staff_operations import (
    SHIFT_PRESETS, _shift_options_for_role, _staffing_names, _monday_for,
    _week_range_label, NORMAL_SHIFT_CAPACITY, SPECIAL_SHIFT_LABELS,
    _eligible_users, _special_label, _shift_category,
    _weekly_hours_table, _first_name, _schedule_display_table,
    _has_approved_time_off,
)


def apply_migration():
    sql = Path("migrations/012_staff_operations.sql").read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    connection = connect_database(); cursor = connection.cursor()
    try:
        for statement in statements:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()


def apply_name_migration():
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT COLUMN_NAME FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='staff_users'
                 AND COLUMN_NAME IN ('first_name','last_name')"""
        )
        existing = {row[0] for row in cursor.fetchall()}
        sql = Path("migrations/013_staff_first_last_name.sql").read_text(encoding="utf-8")
        statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
        for statement in statements:
            if "ADD COLUMN first_name" in statement and "first_name" in existing:
                continue
            if "ADD COLUMN last_name" in statement and "last_name" in existing:
                continue
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()


def apply_boarding_defaults():
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT COLUMN_NAME, COLUMN_DEFAULT FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='boarding_care_profiles'
                 AND COLUMN_NAME IN ('breakfast_required','dinner_required')"""
        )
        defaults = {row[0]: str(row[1]) for row in cursor.fetchall()}
        if defaults.get("breakfast_required") != "1" or defaults.get("dinner_required") != "1":
            sql = Path("migrations/014_boarding_meal_defaults.sql").read_text(encoding="utf-8")
            for statement in [item.strip() for item in sql.split(";") if item.strip()]:
                cursor.execute(statement)
            connection.commit()
    finally:
        cursor.close(); connection.close()


def verify_schema():
    expected = {
        "staff_users", "operations_tasks", "work_shifts",
        "operations_audit_log", "notification_preferences", "schedule_holidays",
        "employee_normal_schedules", "time_off_requests",
        "boarding_reservations",
    }
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        )
        actual = {row[0] for row in cursor.fetchall()}
        missing = expected - actual
        if missing:
            raise AssertionError(f"Missing tables: {sorted(missing)}")
    finally:
        cursor.close(); connection.close()


if __name__ == "__main__":
    for source in (
        "app.py", "auth.py", "operations_service.py", "components/sidebar.py",
        "views/staff_operations.py", "views/boarding_care.py",
        "views/dashboard.py", "views/attendance.py", "views/dog_management.py",
        "database.py",
    ):
        py_compile.compile(source, doraise=True)
    encoded = hash_password("long-test-password")
    assert verify_password("long-test-password", encoded)
    assert not verify_password("incorrect", encoded)
    assert len(_shift_options_for_role("Crew")) == 4
    assert len(_shift_options_for_role("Office")) == 3
    assert len(_shift_options_for_role("Cross-Trained")) == 7
    assert len(_shift_options_for_role("Boss")) == 7
    assert len(_shift_options_for_role("Developer")) == 7
    assert len(_shift_options_for_role("Crew", "AM")) == 2
    assert len(_shift_options_for_role("Crew", "PM")) == 2
    assert len(_shift_options_for_role("Office", "AM")) == 2
    assert len(_shift_options_for_role("Office", "PM")) == 1
    assert len(_shift_options_for_role("Cross-Trained", "AM")) == 4
    assert len(_shift_options_for_role("Cross-Trained", "PM")) == 3
    import pandas as pd
    empty_shifts = pd.DataFrame(columns=["department", "starts_at", "ends_at", "display_name"])
    empty_shifts["starts_at"] = pd.to_datetime(empty_shifts["starts_at"])
    empty_shifts["ends_at"] = pd.to_datetime(empty_shifts["ends_at"])
    assert _staffing_names(empty_shifts, "Office", "AM") == []
    assert len(_shift_options_for_role("Crew", "AM", True)) == 1
    assert len(_shift_options_for_role("Office", "PM", True)) == 1
    assert len(_shift_options_for_role("Cross-Trained", "AM", True)) == 2
    assert _shift_options_for_role("Crew", "AM", True) == ["7:00 AM–11:00 AM"]
    assert _shift_options_for_role("Office", "PM", True) == ["Office 3:00 PM–7:00 PM"]
    assert _special_label("Crew", "PM") == "3:00 PM–7:00 PM"
    assert _special_label("Office", "AM") == "Office 7:00 AM–11:00 AM"
    weekend_shift = pd.DataFrame({
        "department": ["Crew"],
        "starts_at": pd.to_datetime(["2026-08-15 08:00:00"]),
        "ends_at": pd.to_datetime(["2026-08-15 11:30:00"]),
        "display_name": ["Test Employee"],
    })
    assert _staffing_names(weekend_shift, "Crew", "AM", backup=True) == []
    assert _staffing_names(weekend_shift, "Crew", "AM") == ["Test"]
    assert _shift_category({
        "starts_at": pd.Timestamp("2026-08-13 08:00"),
        "ends_at": pd.Timestamp("2026-08-13 11:30"),
        "department": "Crew",
    }) == "AM Crew Backup"
    meal_test_date = __import__("datetime").date(2026, 8, 13)  # Thursday
    meal_test = pd.DataFrame({
        "boarding_stay_id": [1, 2],
        "dinner_required": [1, 1],
        "planned_checkout_datetime": pd.to_datetime([
            "2026-08-13 17:00", "2026-08-14 09:00",
        ]),
        "actual_checkout_datetime": pd.to_datetime([None, None]),
    })
    assert list(_meal_roster(meal_test, "Dinner", meal_test_date)["boarding_stay_id"]) == [2]
    assert len(_meal_roster(meal_test, "Dinner", meal_test_date, holiday_hours=True)) == 2
    saturday = __import__("datetime").date(2026, 8, 15)
    assert len(_meal_roster(meal_test, "Dinner", saturday)) == 2
    permission_now = pd.Timestamp("2026-08-13 10:00")
    active_shift = pd.DataFrame({
        "starts_at": pd.to_datetime(["2026-08-13 08:00"]),
        "ends_at": pd.to_datetime(["2026-08-13 12:00"]),
    })
    assert _can_edit_boarding(
        {"role": "Crew"}, active_shift, permission_now
    )
    assert not _can_edit_boarding(
        {"role": "Crew"}, active_shift, pd.Timestamp("2026-08-13 13:00")
    )
    assert _can_edit_boarding(
        {"role": "Boss"}, pd.DataFrame(), pd.Timestamp("2026-08-13 03:00")
    )
    assert _can_edit_boarding(
        {"role": "Developer"}, pd.DataFrame(), pd.Timestamp("2026-08-13 03:00")
    )
    sibling_test = pd.DataFrame({
        "dog_id": [1, 2, 3],
        "sibling_group_id": [10, 10, None],
    })
    assert _has_boarding_sibling(sibling_test, sibling_test.iloc[0])
    assert not _has_boarding_sibling(sibling_test, sibling_test.iloc[2])
    schedule_sort_test = pd.DataFrame({
        "starts_at": pd.to_datetime([
            "2026-08-11 14:00", "2026-08-10 14:00", "2026-08-10 06:45",
        ]),
        "ends_at": pd.to_datetime([
            "2026-08-11 19:00", "2026-08-10 19:00", "2026-08-10 12:00",
        ]),
        "display_name": ["PM Next", "PM First", "AM First"],
        "department": ["Crew", "Crew", "Crew"],
        "notes": [None, None, None],
    })
    assert list(_schedule_display_table(schedule_sort_test)["Employee"]) == [
        "AM", "PM", "PM",
    ]
    hours_test = pd.DataFrame({
        "user_id": [1, 1, 2],
        "display_name": ["Sam Test", "Sam Test", "Alex Test"],
        "starts_at": pd.to_datetime([
            "2026-08-10 06:45", "2026-08-10 14:00", "2026-08-10 08:00"
        ]),
        "ends_at": pd.to_datetime([
            "2026-08-10 12:00", "2026-08-10 19:00", "2026-08-10 11:30"
        ]),
    })
    hours_summary = _weekly_hours_table(hours_test, __import__("datetime").date(2026, 8, 10))
    assert float(hours_summary[hours_summary.Employee == "Sam Test"].Hours.iloc[0]) == 10.25
    assert _first_name("Sam Martinez") == "Sam"
    approved_test = pd.DataFrame({
        "user_id": [1], "start_date": [__import__("datetime").date(2026, 8, 10)],
        "end_date": [__import__("datetime").date(2026, 8, 12)], "period": ["AM"]
    })
    assert _has_approved_time_off(
        approved_test, 1, __import__("datetime").date(2026, 8, 11), "AM"
    )
    assert not _has_approved_time_off(
        approved_test, 1, __import__("datetime").date(2026, 8, 11), "PM"
    )
    assert _monday_for(__import__("datetime").date(2026, 8, 13)) == __import__("datetime").date(2026, 8, 10)
    assert _monday_for(__import__("datetime").date(2026, 8, 10)) == __import__("datetime").date(2026, 8, 10)
    assert _week_range_label(__import__("datetime").date(2026, 8, 10)) == "08/10/2026–08/16/2026"
    assert NORMAL_SHIFT_CAPACITY["Crew AM — 6:45 AM–12:00 PM"] == 2
    assert NORMAL_SHIFT_CAPACITY["Back Up AM — 8:00 AM–11:30 AM"] == 1
    assert NORMAL_SHIFT_CAPACITY["AM Office — 6:45 AM–12:00 PM"] == 1
    assert NORMAL_SHIFT_CAPACITY["Office Back Up — 6:45 AM–10:30 AM"] == 1
    role_test_users = pd.DataFrame({
        "role": ["Crew", "Office", "Cross-Trained", "Boss", "Developer"],
        "user_id": [1, 2, 3, 4, 5],
    })
    assert set(_eligible_users(role_test_users, "Crew")["user_id"]) == {1, 3, 4, 5}
    assert set(_eligible_users(role_test_users, "Office")["user_id"]) == {2, 3, 4, 5}
    validate_credential("123", "Crew")
    validate_credential("long-test-password", "Developer")
    validate_credential("boss-test-password", "Boss")
    try:
        validate_credential("abcd", "Crew")
        raise AssertionError("Non-numeric worker PIN was accepted")
    except ValueError:
        pass
    try:
        validate_credential("1234", "Crew")
        raise AssertionError("Worker PIN longer than 3 digits was accepted")
    except ValueError:
        pass
    apply_migration()
    apply_name_migration()
    apply_boarding_defaults()
    connection = connect_database(); cursor = connection.cursor()
    try:
        sql = Path("migrations/015_schedule_holidays.sql").read_text(encoding="utf-8")
        for statement in [item.strip() for item in sql.split(";") if item.strip()]:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()
    connection = connect_database(); cursor = connection.cursor()
    try:
        sql = Path("migrations/016_employee_normal_schedules.sql").read_text(encoding="utf-8")
        for statement in [item.strip() for item in sql.split(";") if item.strip()]:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()
    connection = connect_database(); cursor = connection.cursor()
    try:
        sql = Path("migrations/017_time_off_requests.sql").read_text(encoding="utf-8")
        for statement in [item.strip() for item in sql.split(";") if item.strip()]:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()
    connection = connect_database(); cursor = connection.cursor()
    try:
        sql = Path("migrations/018_boarding_reservations.sql").read_text(encoding="utf-8")
        for statement in [item.strip() for item in sql.split(";") if item.strip()]:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close(); connection.close()
    verify_schema()
    arrivals, departures = load_todays_boarding_movements()
    assert list(arrivals.columns) == ["Dog Name", "Breed", "Room Number"]
    assert list(departures.columns) == [
        "Dog Name", "Breed", "AM or PM Pickup", "Room Number"
    ]
    tomorrow_arrivals, tomorrow_departures = load_day_summary(
        __import__("datetime").date.today() + __import__("datetime").timedelta(days=1)
    )
    assert list(tomorrow_arrivals.columns) == ["Dog Name", "Breed", "Room Name"]
    assert list(tomorrow_departures.columns) == [
        "Dog Name", "Breed", "Room Name", "AM or PM"
    ]
    print("PASS: syntax, password hashing, migration, and operations schema")
