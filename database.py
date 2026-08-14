import mysql.connector
import pandas as pd
import os
from datetime import date, datetime, time
from pathlib import Path
import tomllib



# =============================================
# Database Connection
# =============================================

def connect_database():
    local_settings = {}
    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        with secrets_path.open("rb") as secrets_file:
            local_settings = tomllib.load(secrets_file).get("database", {})

    def setting(environment_name, secret_name, default=None):
        return os.getenv(environment_name) or local_settings.get(secret_name) or default

    password = setting("DB_PASSWORD", "password")
    if not password:
        raise RuntimeError(
            "Database password is not configured. Set DB_PASSWORD or add "
            "[database].password to .streamlit/secrets.toml."
        )
    connection = mysql.connector.connect(
        host=setting("DB_HOST", "host", "localhost"),
        port=int(setting("DB_PORT", "port", 3306)),
        user=setting("DB_USER", "user", "root"),
        password=password,
        database=setting("DB_NAME", "name", "Dog_daycare"),
    )

    return connection


# =============================================
# Load Today's Attendance
# =============================================

def load_dogs():

    sync_active_boarding_attendance()
    connection = connect_database()

    query = """
    SELECT
        da.attendance_id,
        da.attendance_date,

        CASE
            WHEN da.visit_type = 'Boarding'
            THEN 1
            ELSE 0
        END AS boarding_status,

        da.assigned_room_id,
        r.room_number AS assigned_room_number,

        bs.boarding_stay_id,
        bs.check_in_datetime AS boarding_check_in,
        bs.planned_checkout_datetime AS boarding_check_out,
        bs.stay_status AS boarding_stay_status,

        di.*

    FROM daily_attendance AS da

    INNER JOIN dogs_info AS di
        ON da.dog_id = di.dog_id

    LEFT JOIN rooms AS r
        ON da.assigned_room_id = r.room_id

    LEFT JOIN boarding_stays AS bs
        ON da.boarding_stay_id = bs.boarding_stay_id

    WHERE da.attendance_date = CURDATE()
    AND da.check_out_time IS NULL
    """

    dogs_df = pd.read_sql(query, connection)

    connection.close()

    return dogs_df


# =============================================
# Load Rooms
# =============================================

def load_rooms():

    connection = connect_database()

    query = "SELECT * FROM rooms"

    rooms_df = pd.read_sql(query, connection)

    connection.close()

    return rooms_df


# =============================================
# Update Room Availability
# =============================================

def update_room_availability(room_statuses):

    prepared_statuses = [
        (1 if bool(is_available) else 0, int(room_id))
        for room_id, is_available in room_statuses.items()
    ]

    if not prepared_statuses:
        return 0

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.executemany(
            """
            UPDATE rooms
            SET status = %s
            WHERE room_id = %s
            """,
            prepared_statuses
        )
        changed_count = cursor.rowcount
        connection.commit()
        return changed_count
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Load Sibling Groups
# =============================================

def load_sibling_group():

    connection = connect_database()

    query = "SELECT * FROM sibling_group"

    sibling_group_df = pd.read_sql(query, connection)

    connection.close()

    return sibling_group_df


# =============================================
# Add Dog to Today's Attendance
# =============================================

def add_attendance(dog_id, visit_type, assigned_room_id=None):

    add_attendance_records(
        [
            {
                "dog_id": dog_id,
                "visit_type": visit_type,
                "assigned_room_id": assigned_room_id
            }
        ]
    )


def add_attendance_records(records):

    prepared_records = []

    for record in records:

        dog_id = int(record["dog_id"])
        visit_type = str(record["visit_type"]).strip()
        assigned_room_id = record.get("assigned_room_id")

        if visit_type not in {"Daycare", "Boarding"}:
            raise ValueError("Visit type must be Daycare or Boarding.")

        if visit_type == "Boarding" and assigned_room_id is None:
            raise ValueError("Boarding dogs must have an assigned room.")

        if assigned_room_id is not None:
            assigned_room_id = int(assigned_room_id)

        check_in_datetime = record.get("check_in_datetime")
        planned_checkout_datetime = record.get(
            "planned_checkout_datetime"
        )

        if visit_type == "Boarding":
            check_in_datetime = check_in_datetime or datetime.now()
            planned_checkout_datetime = (
                planned_checkout_datetime
                or datetime.combine(date.today(), time(23, 59, 59))
            )

            if planned_checkout_datetime < check_in_datetime:
                raise ValueError(
                    "Boarding checkout must be after check-in."
                )

        prepared_records.append(
            {
                "dog_id": dog_id,
                "visit_type": visit_type,
                "assigned_room_id": assigned_room_id,
                "check_in_datetime": check_in_datetime,
                "planned_checkout_datetime": planned_checkout_datetime
            }
        )

    if not prepared_records:
        raise ValueError("At least one attendance record is required.")

    connection = connect_database()

    cursor = connection.cursor()

    try:

        for record in prepared_records:
            boarding_stay_id = None

            if record["visit_type"] == "Boarding":
                cursor.execute(
                    """
                    INSERT INTO boarding_stays
                    (
                        dog_id,
                        check_in_datetime,
                        planned_checkout_datetime,
                        assigned_room_id,
                        stay_status
                    )
                    VALUES (%s, %s, %s, %s, 'Checked In')
                    """,
                    (
                        record["dog_id"],
                        record["check_in_datetime"],
                        record["planned_checkout_datetime"],
                        record["assigned_room_id"]
                    )
                )
                boarding_stay_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO daily_attendance
                (
                    dog_id,
                    attendance_date,
                    visit_type,
                    assigned_room_id,
                    boarding_stay_id,
                    check_in_time
                )
                VALUES (%s, CURDATE(), %s, %s, %s, %s)
                """,
                (
                    record["dog_id"],
                    record["visit_type"],
                    record["assigned_room_id"],
                    boarding_stay_id,
                    record["check_in_datetime"]
                )
            )

        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        cursor.close()
        connection.close()


# =============================================
# Edit or End Boarding Stay
# =============================================

def update_boarding_stay(
    boarding_stay_id,
    check_in_datetime,
    planned_checkout_datetime,
    assigned_room_id
):

    boarding_stay_id = int(boarding_stay_id)
    assigned_room_id = int(assigned_room_id)

    if planned_checkout_datetime < check_in_datetime:
        raise ValueError("Boarding checkout must be after check-in.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE boarding_stays
            SET
                check_in_datetime = %s,
                planned_checkout_datetime = %s,
                assigned_room_id = %s,
                updated_at = NOW()
            WHERE boarding_stay_id = %s
            AND stay_status = 'Checked In'
            """,
            (
                check_in_datetime,
                planned_checkout_datetime,
                assigned_room_id,
                boarding_stay_id
            )
        )

        if cursor.rowcount != 1:
            raise ValueError("That boarding stay is no longer active.")

        cursor.execute(
            """
            UPDATE daily_attendance
            SET assigned_room_id = %s
            WHERE boarding_stay_id = %s
            AND attendance_date = CURDATE()
            AND check_out_time IS NULL
            """,
            (assigned_room_id, boarding_stay_id)
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def update_boarding_stays(
    boarding_stay_ids,
    check_in_datetime,
    planned_checkout_datetime,
    assigned_room_id
):

    prepared_stay_ids = list(dict.fromkeys(
        int(boarding_stay_id)
        for boarding_stay_id in boarding_stay_ids
    ))

    if not prepared_stay_ids:
        raise ValueError("Select at least one active boarding stay.")

    assigned_room_id = int(assigned_room_id)

    if planned_checkout_datetime < check_in_datetime:
        raise ValueError("Boarding checkout must be after check-in.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        for boarding_stay_id in prepared_stay_ids:
            cursor.execute(
                """
                UPDATE boarding_stays
                SET
                    check_in_datetime = %s,
                    planned_checkout_datetime = %s,
                    assigned_room_id = %s,
                    updated_at = NOW()
                WHERE boarding_stay_id = %s
                AND stay_status = 'Checked In'
                """,
                (
                    check_in_datetime,
                    planned_checkout_datetime,
                    assigned_room_id,
                    boarding_stay_id
                )
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "One of those boarding stays is no longer active."
                )

            cursor.execute(
                """
                UPDATE daily_attendance
                SET assigned_room_id = %s
                WHERE boarding_stay_id = %s
                AND attendance_date = CURDATE()
                AND check_out_time IS NULL
                """,
                (assigned_room_id, boarding_stay_id)
            )

        connection.commit()
        return len(prepared_stay_ids)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def end_boarding_stay(attendance_id, switch_to_daycare=False):

    attendance_id = int(attendance_id)
    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT boarding_stay_id
            FROM daily_attendance
            WHERE attendance_id = %s
            AND attendance_date = CURDATE()
            AND visit_type = 'Boarding'
            AND check_out_time IS NULL
            FOR UPDATE
            """,
            (attendance_id,)
        )
        attendance_row = cursor.fetchone()

        if attendance_row is None:
            raise ValueError("That active boarding attendance was not found.")

        boarding_stay_id = attendance_row[0]

        if boarding_stay_id is not None:
            cursor.execute(
                """
                UPDATE boarding_stays
                SET
                    stay_status = 'Checked Out',
                    actual_checkout_datetime = NOW(),
                    planned_checkout_datetime = LEAST(
                        planned_checkout_datetime,
                        NOW()
                    ),
                    updated_at = NOW()
                WHERE boarding_stay_id = %s
                AND stay_status = 'Checked In'
                """,
                (int(boarding_stay_id),)
            )

        if switch_to_daycare:
            cursor.execute(
                """
                UPDATE daily_attendance
                SET
                    visit_type = 'Daycare',
                    assigned_room_id = NULL,
                    boarding_stay_id = NULL,
                    check_out_time = NULL
                WHERE attendance_id = %s
                """,
                (attendance_id,)
            )
        else:
            cursor.execute(
                """
                UPDATE daily_attendance
                SET check_out_time = NOW()
                WHERE attendance_id = %s
                """,
                (attendance_id,)
            )

        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def end_boarding_stays(attendance_ids, switch_to_daycare=False):

    prepared_attendance_ids = list(dict.fromkeys(
        int(attendance_id)
        for attendance_id in attendance_ids
    ))

    if not prepared_attendance_ids:
        raise ValueError("Select at least one active boarder.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        for attendance_id in prepared_attendance_ids:
            cursor.execute(
                """
                SELECT boarding_stay_id
                FROM daily_attendance
                WHERE attendance_id = %s
                AND attendance_date = CURDATE()
                AND visit_type = 'Boarding'
                AND check_out_time IS NULL
                FOR UPDATE
                """,
                (attendance_id,)
            )
            attendance_row = cursor.fetchone()

            if attendance_row is None:
                raise ValueError(
                    "One of those active boarding records was not found."
                )

            boarding_stay_id = attendance_row[0]

            if boarding_stay_id is not None:
                cursor.execute(
                    """
                    UPDATE boarding_stays
                    SET
                        stay_status = 'Checked Out',
                        actual_checkout_datetime = NOW(),
                        planned_checkout_datetime = LEAST(
                            planned_checkout_datetime,
                            NOW()
                        ),
                        updated_at = NOW()
                    WHERE boarding_stay_id = %s
                    AND stay_status = 'Checked In'
                    """,
                    (int(boarding_stay_id),)
                )

                if cursor.rowcount != 1:
                    raise ValueError(
                        "One of those boarding stays is no longer active."
                    )

            if switch_to_daycare:
                cursor.execute(
                    """
                    UPDATE daily_attendance
                    SET
                        visit_type = 'Daycare',
                        assigned_room_id = NULL,
                        boarding_stay_id = NULL,
                        check_out_time = NULL
                    WHERE attendance_id = %s
                    """,
                    (attendance_id,)
                )
            else:
                cursor.execute(
                    """
                    UPDATE daily_attendance
                    SET check_out_time = NOW()
                    WHERE attendance_id = %s
                    """,
                    (attendance_id,)
                )

        connection.commit()
        return len(prepared_attendance_ids)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def switch_daycare_to_boarding(records):

    prepared_records = []

    for record in records:
        attendance_id = int(record["attendance_id"])
        assigned_room_id = int(record["assigned_room_id"])
        check_in_datetime = record.get("check_in_datetime") or datetime.now()
        planned_checkout_datetime = record["planned_checkout_datetime"]

        if planned_checkout_datetime <= check_in_datetime:
            raise ValueError("Boarding checkout must be after check-in.")

        prepared_records.append(
            (
                attendance_id,
                assigned_room_id,
                check_in_datetime,
                planned_checkout_datetime
            )
        )

    if not prepared_records:
        raise ValueError("Select at least one Daycare dog.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        for (
            attendance_id,
            assigned_room_id,
            check_in_datetime,
            planned_checkout_datetime
        ) in prepared_records:
            cursor.execute(
                """
                SELECT dog_id
                FROM daily_attendance
                WHERE attendance_id = %s
                AND attendance_date = CURDATE()
                AND visit_type = 'Daycare'
                AND check_out_time IS NULL
                FOR UPDATE
                """,
                (attendance_id,)
            )
            attendance_row = cursor.fetchone()

            if attendance_row is None:
                raise ValueError(
                    "One of those active Daycare records was not found."
                )

            dog_id = int(attendance_row[0])
            cursor.execute(
                """
                INSERT INTO boarding_stays
                (
                    dog_id,
                    check_in_datetime,
                    planned_checkout_datetime,
                    assigned_room_id,
                    stay_status
                )
                VALUES (%s, %s, %s, %s, 'Checked In')
                """,
                (
                    dog_id,
                    check_in_datetime,
                    planned_checkout_datetime,
                    assigned_room_id
                )
            )
            boarding_stay_id = int(cursor.lastrowid)
            cursor.execute(
                """
                UPDATE daily_attendance
                SET
                    visit_type = 'Boarding',
                    assigned_room_id = %s,
                    boarding_stay_id = %s,
                    check_in_time = %s,
                    check_out_time = NULL
                WHERE attendance_id = %s
                """,
                (
                    assigned_room_id,
                    boarding_stay_id,
                    check_in_datetime,
                    attendance_id
                )
            )

        connection.commit()
        return len(prepared_records)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Remove Dog from Today's Attendance
# =============================================

def remove_attendance(attendance_id):

    return remove_attendance_records([attendance_id]) == 1


def remove_attendance_records(attendance_ids):

    prepared_ids = [
        (int(attendance_id),)
        for attendance_id in attendance_ids
    ]

    if not prepared_ids:
        raise ValueError("At least one attendance record is required.")

    connection = connect_database()
    cursor = connection.cursor()

    query = """
        DELETE FROM daily_attendance
        WHERE attendance_id = %s
        AND attendance_date = CURDATE()
    """

    try:

        cursor.executemany(query, prepared_ids)
        removed_count = cursor.rowcount
        connection.commit()

        return removed_count

    except Exception:

        connection.rollback()
        raise

    finally:

        cursor.close()
        connection.close()


# =============================================
# Load Dogs Not Checked In Today
# =============================================

def load_available_dogs():

    connection = connect_database()

    query = """
        SELECT *
        FROM dogs_info
        WHERE active_status = 1
        AND dog_id NOT IN
        (
            SELECT dog_id
            FROM daily_attendance
            WHERE attendance_date = CURDATE()
        )
        ORDER BY dog_name;
    """

    available_dogs_df = pd.read_sql(query, connection)

    connection.close()

    return available_dogs_df


# =============================================
# Load All Dog Profiles
# =============================================

def load_all_dogs():

    connection = connect_database()

    query = """
        SELECT *
        FROM dogs_info
        ORDER BY dog_name
    """

    dogs_df = pd.read_sql(query, connection)
    connection.close()

    return dogs_df


def load_todays_boarding_movements():
    """Return clean arrival and departure tables for today's dashboard."""
    connection = connect_database()
    try:
        arrivals = pd.read_sql(
            """SELECT di.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(di.dog_breed, ''), 'Not recorded') AS Breed,
                      COALESCE(CAST(r.room_number AS CHAR), 'Unassigned') AS `Room Number`
               FROM boarding_stays bs
               JOIN dogs_info di ON di.dog_id = bs.dog_id
               LEFT JOIN rooms r ON r.room_id = bs.assigned_room_id
               WHERE DATE(bs.check_in_datetime) = CURDATE()
                 AND bs.stay_status <> 'Cancelled'
               ORDER BY bs.check_in_datetime, di.dog_name""",
            connection
        )
        departures = pd.read_sql(
            """SELECT di.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(di.dog_breed, ''), 'Not recorded') AS Breed,
                      CASE WHEN HOUR(bs.planned_checkout_datetime) < 12
                           THEN 'AM' ELSE 'PM' END AS `AM or PM Pickup`,
                      COALESCE(CAST(r.room_number AS CHAR), 'Unassigned') AS `Room Number`
               FROM boarding_stays bs
               JOIN dogs_info di ON di.dog_id = bs.dog_id
               LEFT JOIN rooms r ON r.room_id = bs.assigned_room_id
               WHERE DATE(bs.planned_checkout_datetime) = CURDATE()
                 AND bs.stay_status <> 'Cancelled'
               ORDER BY bs.planned_checkout_datetime, di.dog_name""",
            connection
        )
        planned_arrivals = pd.read_sql(
            """SELECT di.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(di.dog_breed, ''), 'Not recorded') AS Breed,
                      COALESCE(CAST(r.room_number AS CHAR), 'Unassigned') AS `Room Number`
               FROM boarding_reservations br
               JOIN dogs_info di ON di.dog_id=br.dog_id
               LEFT JOIN rooms r ON r.room_id=br.room_id
               WHERE br.arrival_date=CURDATE() AND br.status='Planned'""",
            connection
        )
        planned_departures = pd.read_sql(
            """SELECT di.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(di.dog_breed, ''), 'Not recorded') AS Breed,
                      br.pickup_period AS `AM or PM Pickup`,
                      COALESCE(CAST(r.room_number AS CHAR), 'Unassigned') AS `Room Number`
               FROM boarding_reservations br
               JOIN dogs_info di ON di.dog_id=br.dog_id
               LEFT JOIN rooms r ON r.room_id=br.room_id
               WHERE br.departure_date=CURDATE() AND br.status='Planned'""",
            connection
        )
        arrivals = pd.concat([arrivals, planned_arrivals], ignore_index=True).drop_duplicates("Dog Name")
        departures = pd.concat([departures, planned_departures], ignore_index=True).drop_duplicates("Dog Name")
        return arrivals, departures
    finally:
        connection.close()


# =============================================
# Load Analytics Data
# =============================================

def load_analytics_data(start_date, end_date):

    connection = connect_database()
    date_params = (start_date, end_date)

    try:
        records_df = pd.read_sql(
            """
            SELECT
                record_date,
                status,
                revision_number,
                finalized_at,
                updated_at,
                update_reason
            FROM daily_assignment_records
            WHERE record_date BETWEEN %s AND %s
            AND status = 'Finalized'
            ORDER BY record_date
            """,
            connection,
            params=date_params
        )
        attendance_df = pd.read_sql(
            """
            SELECT DISTINCT
                da.attendance_date,
                da.dog_id,
                di.dog_name,
                di.dog_nickname,
                di.play_group,
                di.active_status,
                da.visit_type,
                da.boarding_stay_id
            FROM daily_attendance AS da
            INNER JOIN dogs_info AS di
                ON di.dog_id = da.dog_id
            INNER JOIN daily_assignment_records AS dar
                ON dar.record_date = da.attendance_date
                AND dar.status = 'Finalized'
            WHERE da.attendance_date BETWEEN %s AND %s
            ORDER BY da.attendance_date, di.dog_name
            """,
            connection,
            params=date_params
        )
        assignments_df = pd.read_sql(
            """
            SELECT
                a.assignment_date,
                a.dog_id,
                di.dog_name,
                di.play_group,
                a.room_id,
                r.room_number,
                r.room_name,
                r.room_type,
                a.assignment_type,
                a.override_reason
            FROM assignments AS a
            INNER JOIN dogs_info AS di
                ON di.dog_id = a.dog_id
            INNER JOIN rooms AS r
                ON r.room_id = a.room_id
            INNER JOIN daily_assignment_records AS dar
                ON dar.record_date = a.assignment_date
                AND dar.status = 'Finalized'
            WHERE a.assignment_date BETWEEN %s AND %s
            ORDER BY a.assignment_date, r.room_id, di.dog_name
            """,
            connection,
            params=date_params
        )
        boarding_stays_df = pd.read_sql(
            """
            SELECT
                bs.boarding_stay_id,
                bs.dog_id,
                di.dog_name,
                di.dog_nickname,
                bs.check_in_datetime,
                bs.planned_checkout_datetime,
                bs.actual_checkout_datetime,
                bs.assigned_room_id,
                r.room_number,
                r.room_name,
                bs.stay_status
            FROM boarding_stays AS bs
            INNER JOIN dogs_info AS di
                ON di.dog_id = bs.dog_id
            INNER JOIN rooms AS r
                ON r.room_id = bs.assigned_room_id
            WHERE DATE(bs.check_in_datetime) BETWEEN %s AND %s
            ORDER BY bs.check_in_datetime, di.dog_name
            """,
            connection,
            params=date_params
        )
        all_visits_df = pd.read_sql(
            """
            SELECT
                da.attendance_date,
                da.dog_id,
                da.visit_type
            FROM daily_attendance AS da
            ORDER BY da.attendance_date
            """,
            connection
        )
        all_boarding_stays_df = pd.read_sql(
            """
            SELECT
                boarding_stay_id,
                dog_id,
                check_in_datetime,
                planned_checkout_datetime,
                actual_checkout_datetime,
                assigned_room_id
            FROM boarding_stays
            ORDER BY check_in_datetime
            """,
            connection
        )
        dogs_df = pd.read_sql(
            """
            SELECT
                dog_id,
                dog_name,
                dog_nickname,
                play_group,
                active_status
            FROM dogs_info
            ORDER BY dog_name
            """,
            connection
        )

        return {
            "records": records_df,
            "attendance": attendance_df,
            "assignments": assignments_df,
            "boarding_stays": boarding_stays_df,
            "all_visits": all_visits_df,
            "all_boarding_stays": all_boarding_stays_df,
            "dogs": dogs_df
        }
    finally:
        connection.close()


# =============================================
# Synchronize Active Boarding Stays
# =============================================

def sync_active_boarding_attendance():

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE boarding_stays
            SET
                stay_status = 'Checked Out',
                actual_checkout_datetime = planned_checkout_datetime,
                updated_at = NOW()
            WHERE stay_status = 'Checked In'
            AND actual_checkout_datetime IS NULL
            AND planned_checkout_datetime < NOW()
            """
        )
        cursor.execute(
            """
            UPDATE daily_attendance AS da
            INNER JOIN boarding_stays AS bs
                ON bs.boarding_stay_id = da.boarding_stay_id
            SET da.check_out_time = COALESCE(
                bs.actual_checkout_datetime,
                bs.planned_checkout_datetime
            )
            WHERE bs.stay_status = 'Checked Out'
            AND da.visit_type = 'Boarding'
            AND da.check_out_time IS NULL
            """
        )
        cursor.execute(
            """
            INSERT INTO daily_attendance
            (
                dog_id,
                attendance_date,
                visit_type,
                assigned_room_id,
                boarding_stay_id,
                check_in_time
            )
            SELECT
                bs.dog_id,
                CURDATE(),
                'Boarding',
                bs.assigned_room_id,
                bs.boarding_stay_id,
                bs.check_in_datetime
            FROM boarding_stays AS bs
            WHERE bs.stay_status = 'Checked In'
            AND bs.actual_checkout_datetime IS NULL
            AND bs.check_in_datetime <= NOW()
            AND bs.planned_checkout_datetime >= NOW()
            ON DUPLICATE KEY UPDATE
                visit_type = 'Boarding',
                assigned_room_id = VALUES(assigned_room_id),
                boarding_stay_id = VALUES(boarding_stay_id),
                check_out_time = NULL
            """
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Activate or Deactivate Dog Profile
# =============================================

def set_dog_active_status(dog_id, is_active):

    dog_id = int(dog_id)
    active_status = 1 if bool(is_active) else 0

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE dogs_info
            SET active_status = %s
            WHERE dog_id = %s
            """,
            (active_status, dog_id)
        )
        connection.commit()
        return cursor.rowcount == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Add New Dog Profile
# =============================================

def add_dog_profile(profile):

    dog_name = str(profile["dog_name"]).strip()
    dog_nickname = str(profile.get("dog_nickname") or "").strip() or None
    dog_breed = str(profile.get("dog_breed") or "").strip() or None
    color = str(profile.get("color") or "").strip() or None
    gender = str(profile["gender"]).strip().upper()
    date_of_birth = profile.get("date_of_birth")
    size_class = str(profile["size_class"]).strip()
    play_group = str(profile["play_group"]).strip()
    crate_size = str(profile.get("crate_size") or "").strip() or None
    notes = str(profile.get("Notes") or "").strip() or None

    if not dog_name:
        raise ValueError("Dog name is required.")
    if len(dog_name) > 50:
        raise ValueError("Dog name must be 50 characters or fewer.")
    if dog_nickname and len(dog_nickname) > 50:
        raise ValueError("Nickname must be 50 characters or fewer.")
    if dog_breed and len(dog_breed) > 30:
        raise ValueError("Breed must be 30 characters or fewer.")
    if color and len(color) > 50:
        raise ValueError("Color must be 50 characters or fewer.")
    if gender not in {"M", "F"}:
        raise ValueError("Gender must be Male or Female.")
    if not size_class or len(size_class) > 20:
        raise ValueError("A valid size class is required.")
    if play_group not in {"Big", "Small", "Separate"}:
        raise ValueError("Play group must be Big, Small, or Separate.")
    if notes and len(notes) > 200:
        raise ValueError("Notes must be 200 characters or fewer.")
    if bool(profile.get("crate_allowed")) and crate_size not in {
        "XS", "SM", "M", "L", "XL", "XXL"
    }:
        raise ValueError(
            "Select a crate size when Crate allowed is checked."
        )

    boolean_fields = (
        "kennel_allowed",
        "crate_allowed",
        "larger_crate_allowed",
        "suite_allowed",
        "floor_allowed",
        "crate_trained",
        "fence_fighter",
        "fence_jumpers"
    )
    priority_fields = (
        "kennel_priority",
        "crate_priority",
        "suite_priority",
        "floor_priority"
    )
    boolean_values = {
        field: 1 if bool(profile.get(field)) else 0
        for field in boolean_fields
    }
    priority_values = {
        field: int(profile.get(field, 0))
        for field in priority_fields
    }

    if any(
        priority < 0 or priority > 4
        for priority in priority_values.values()
    ):
        raise ValueError("Individual room priorities must be between 0 and 4.")

    for allowed_field, priority_field in (
        ("crate_allowed", "crate_priority"),
        ("kennel_allowed", "kennel_priority"),
        ("suite_allowed", "suite_priority"),
        ("floor_allowed", "floor_priority")
    ):
        if priority_values[priority_field] == 0:
            boolean_values[allowed_field] = 0

    boolean_values["crate_trained"] = boolean_values["crate_allowed"]

    sibling_priority_fields = (
        "shared_suite_priority",
        "shared_floor_priority",
        "shared_kennel_priority"
    )
    sibling_priorities = {
        field: int(profile.get(field, 0))
        for field in sibling_priority_fields
    }

    if not bool(profile.get("keep_together", False)):
        sibling_priorities = {
            field: 0
            for field in sibling_priority_fields
        }
    if any(
        priority < 0 or priority > 3
        for priority in sibling_priorities.values()
    ):
        raise ValueError("Sibling room priorities must be between 0 and 3.")

    query = """
        INSERT INTO dogs_info
        (
            dog_name, dog_nickname, dog_breed, color, gender,
            date_of_birth, size_class, play_group, kennel_allowed,
            crate_allowed, crate_size, larger_crate_allowed,
            suite_allowed, floor_allowed, kennel_priority,
            crate_priority, suite_priority, floor_priority,
            crate_trained, fence_fighter, fence_jumpers, Notes,
            active_status
        )
        VALUES
        (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
        )
    """
    values = (
        dog_name, dog_nickname, dog_breed, color, gender,
        date_of_birth, size_class, play_group,
        boolean_values["kennel_allowed"],
        boolean_values["crate_allowed"], crate_size,
        boolean_values["larger_crate_allowed"],
        boolean_values["suite_allowed"],
        boolean_values["floor_allowed"],
        priority_values["kennel_priority"],
        priority_values["crate_priority"],
        priority_values["suite_priority"],
        priority_values["floor_priority"],
        boolean_values["crate_trained"],
        boolean_values["fence_fighter"],
        boolean_values["fence_jumpers"], notes
    )

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(query, values)
        dog_id = cursor.lastrowid

        sibling_dog_id = profile.get("sibling_dog_id")

        if sibling_dog_id is not None:
            sibling_dog_id = int(sibling_dog_id)
            cursor.execute(
                """
                SELECT sibling_group_id
                FROM dogs_info
                WHERE dog_id = %s
                FOR UPDATE
                """,
                (sibling_dog_id,)
            )
            sibling_row = cursor.fetchone()

            if sibling_row is None:
                raise ValueError("The selected sibling profile was not found.")

            sibling_group_id = sibling_row[0]

            if sibling_group_id is None:
                cursor.execute(
                    """
                    INSERT INTO sibling_group
                    (
                        dog1_id, dog2_id, keep_together,
                        shared_suite_allowed, shared_floor_allowed,
                        shared_kennel_allowed, shared_suite_priority,
                        shared_floor_priority, shared_kennel_priority
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sibling_dog_id,
                        dog_id,
                        1 if profile.get("keep_together", True) else 0,
                        1 if profile.get("shared_suite_allowed")
                        and sibling_priorities["shared_suite_priority"] > 0
                        else 0,
                        1 if profile.get("shared_floor_allowed")
                        and sibling_priorities["shared_floor_priority"] > 0
                        else 0,
                        1 if profile.get("shared_kennel_allowed")
                        and sibling_priorities["shared_kennel_priority"] > 0
                        else 0,
                        sibling_priorities["shared_suite_priority"],
                        sibling_priorities["shared_floor_priority"],
                        sibling_priorities["shared_kennel_priority"]
                    )
                )
                sibling_group_id = cursor.lastrowid
                cursor.execute(
                    """
                    UPDATE dogs_info
                    SET sibling_group_id = %s
                    WHERE dog_id IN (%s, %s)
                    """,
                    (sibling_group_id, sibling_dog_id, dog_id)
                )
            else:
                cursor.execute(
                    """
                    SELECT dog1_id, dog2_id, dog3_id, dog4_id
                    FROM sibling_group
                    WHERE sibling_group_id = %s
                    FOR UPDATE
                    """,
                    (int(sibling_group_id),)
                )
                group_row = cursor.fetchone()

                if group_row is None:
                    raise ValueError("The selected sibling group was not found.")

                empty_columns = [
                    column
                    for column, value in zip(
                        ("dog1_id", "dog2_id", "dog3_id", "dog4_id"),
                        group_row
                    )
                    if value is None
                ]

                if not empty_columns:
                    raise ValueError(
                        "That sibling group already has four dogs."
                    )

                cursor.execute(
                    f"""
                    UPDATE sibling_group
                    SET {empty_columns[0]} = %s
                    WHERE sibling_group_id = %s
                    """,
                    (dog_id, int(sibling_group_id))
                )
                cursor.execute(
                    """
                    UPDATE dogs_info
                    SET sibling_group_id = %s
                    WHERE dog_id = %s
                    """,
                    (int(sibling_group_id), dog_id)
                )

        connection.commit()
        return int(dog_id)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Update Dog Profile
# =============================================

def update_dog_profile(dog_id, profile):

    dog_id = int(dog_id)

    dog_name = str(profile["dog_name"]).strip()
    dog_nickname = str(profile.get("dog_nickname") or "").strip() or None
    dog_breed = str(profile.get("dog_breed") or "").strip() or None
    color = str(profile.get("color") or "").strip() or None
    gender = str(profile["gender"]).strip().upper()
    date_of_birth = profile.get("date_of_birth")
    size_class = str(profile["size_class"]).strip()
    play_group = str(profile["play_group"]).strip()
    notes = str(profile.get("Notes") or "").strip() or None
    crate_size = str(profile.get("crate_size") or "").strip() or None

    if not dog_name:
        raise ValueError("Dog name is required.")
    if len(dog_name) > 50:
        raise ValueError("Dog name must be 50 characters or fewer.")
    if dog_nickname and len(dog_nickname) > 50:
        raise ValueError("Nickname must be 50 characters or fewer.")
    if dog_breed and len(dog_breed) > 30:
        raise ValueError("Breed must be 30 characters or fewer.")
    if color and len(color) > 50:
        raise ValueError("Color must be 50 characters or fewer.")
    if gender not in {"M", "F"}:
        raise ValueError("Gender must be M or F.")
    if not size_class or len(size_class) > 20:
        raise ValueError("A valid size class is required.")
    if play_group not in {"Big", "Small", "Separate"}:
        raise ValueError("Play group must be Big, Small, or Separate.")
    if notes and len(notes) > 200:
        raise ValueError("Notes must be 200 characters or fewer.")
    if bool(profile.get("crate_allowed")) and crate_size not in {
        "XS", "SM", "M", "L", "XL", "XXL"
    }:
        raise ValueError(
            "Select a crate size when Crate allowed is checked."
        )

    boolean_fields = (
        "kennel_allowed",
        "crate_allowed",
        "larger_crate_allowed",
        "suite_allowed",
        "floor_allowed",
        "crate_trained",
        "fence_fighter",
        "fence_jumpers"
    )
    priority_fields = (
        "kennel_priority",
        "crate_priority",
        "suite_priority",
        "floor_priority"
    )

    boolean_values = {
        field: 1 if bool(profile.get(field)) else 0
        for field in boolean_fields
    }
    priority_values = {
        field: int(profile.get(field, 0))
        for field in priority_fields
    }

    if any(
        priority < 0 or priority > 4
        for priority in priority_values.values()
    ):
        raise ValueError("Individual room priorities must be between 0 and 4.")

    for allowed_field, priority_field in (
        ("crate_allowed", "crate_priority"),
        ("kennel_allowed", "kennel_priority"),
        ("suite_allowed", "suite_priority"),
        ("floor_allowed", "floor_priority")
    ):
        if priority_values[priority_field] == 0:
            boolean_values[allowed_field] = 0

    boolean_values["crate_trained"] = boolean_values["crate_allowed"]

    sibling_group_id = profile.get("sibling_group_id")
    sibling_settings = None

    if sibling_group_id is not None:
        sibling_group_id = int(sibling_group_id)
        keep_together = bool(profile.get("keep_together", False))
        sibling_priorities = {
            field: int(profile.get(field, 0))
            for field in (
                "shared_suite_priority",
                "shared_floor_priority",
                "shared_kennel_priority"
            )
        }

        if any(
            priority < 0 or priority > 3
            for priority in sibling_priorities.values()
        ):
            raise ValueError(
                "Sibling room priorities must be between 0 and 3."
            )

        if not keep_together:
            sibling_priorities = {
                field: 0
                for field in sibling_priorities
            }

        sibling_settings = {
            "keep_together": 1 if keep_together else 0,
            "shared_suite_priority": sibling_priorities[
                "shared_suite_priority"
            ],
            "shared_floor_priority": sibling_priorities[
                "shared_floor_priority"
            ],
            "shared_kennel_priority": sibling_priorities[
                "shared_kennel_priority"
            ]
        }

    query = """
        UPDATE dogs_info
        SET
            dog_name = %s,
            dog_nickname = %s,
            dog_breed = %s,
            color = %s,
            gender = %s,
            date_of_birth = %s,
            size_class = %s,
            play_group = %s,
            kennel_allowed = %s,
            crate_allowed = %s,
            crate_size = %s,
            larger_crate_allowed = %s,
            suite_allowed = %s,
            floor_allowed = %s,
            kennel_priority = %s,
            crate_priority = %s,
            suite_priority = %s,
            floor_priority = %s,
            crate_trained = %s,
            fence_fighter = %s,
            fence_jumpers = %s,
            Notes = %s
        WHERE dog_id = %s
    """

    values = (
        dog_name,
        dog_nickname,
        dog_breed,
        color,
        gender,
        date_of_birth,
        size_class,
        play_group,
        boolean_values["kennel_allowed"],
        boolean_values["crate_allowed"],
        crate_size,
        boolean_values["larger_crate_allowed"],
        boolean_values["suite_allowed"],
        boolean_values["floor_allowed"],
        priority_values["kennel_priority"],
        priority_values["crate_priority"],
        priority_values["suite_priority"],
        priority_values["floor_priority"],
        boolean_values["crate_trained"],
        boolean_values["fence_fighter"],
        boolean_values["fence_jumpers"],
        notes,
        dog_id
    )

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(query, values)
        dog_profile_updated = cursor.rowcount == 1

        sibling_settings_updated = False

        if sibling_settings is not None:
            cursor.execute(
                """
                SELECT dog1_id, dog2_id, dog3_id, dog4_id
                FROM sibling_group
                WHERE sibling_group_id = %s
                FOR UPDATE
                """,
                (sibling_group_id,)
            )
            sibling_members = cursor.fetchone()

            if sibling_members is None or dog_id not in {
                int(member_id)
                for member_id in sibling_members
                if member_id is not None
            }:
                raise ValueError(
                    "That sibling group is not linked to this dog."
                )

            cursor.execute(
                """
                UPDATE sibling_group
                SET
                    keep_together = %s,
                    shared_suite_allowed = %s,
                    shared_floor_allowed = %s,
                    shared_kennel_allowed = %s,
                    shared_suite_priority = %s,
                    shared_floor_priority = %s,
                    shared_kennel_priority = %s
                WHERE sibling_group_id = %s
                """,
                (
                    sibling_settings["keep_together"],
                    1 if sibling_settings[
                        "shared_suite_priority"
                    ] > 0 else 0,
                    1 if sibling_settings[
                        "shared_floor_priority"
                    ] > 0 else 0,
                    1 if sibling_settings[
                        "shared_kennel_priority"
                    ] > 0 else 0,
                    sibling_settings["shared_suite_priority"],
                    sibling_settings["shared_floor_priority"],
                    sibling_settings["shared_kennel_priority"],
                    sibling_group_id
                )
            )
            sibling_settings_updated = cursor.rowcount == 1

        connection.commit()
        return dog_profile_updated or sibling_settings_updated
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# =============================================
# Load and Save Daily Nap Assignments
# =============================================

def load_todays_assignments():

    connection = connect_database()
    query = """
        SELECT
            a.assignment_id,
            a.assignment_date,
            a.dog_id,
            di.dog_name,
            di.play_group,
            di.size_class,
            di.sibling_group_id,
            a.room_id,
            r.room_number,
            r.room_name,
            r.room_type,
            da.visit_type,
            a.assignment_type,
            a.override_reason,
            a.finalized_at
        FROM assignments AS a
        INNER JOIN dogs_info AS di
            ON a.dog_id = di.dog_id
        INNER JOIN rooms AS r
            ON a.room_id = r.room_id
        LEFT JOIN daily_attendance AS da
            ON da.dog_id = a.dog_id
            AND da.attendance_date = a.assignment_date
        WHERE a.assignment_date = CURDATE()
        ORDER BY r.room_id, di.dog_name
    """
    assignments_df = pd.read_sql(query, connection)
    connection.close()
    return assignments_df


def load_assignments_by_date(assignment_date):

    connection = connect_database()
    query = """
        SELECT
            a.assignment_id,
            a.assignment_date,
            a.dog_id,
            di.dog_name,
            di.play_group,
            di.size_class,
            di.sibling_group_id,
            a.room_id,
            r.room_number,
            r.room_name,
            r.room_type,
            da.visit_type,
            a.assignment_type,
            a.override_reason,
            a.finalized_at
        FROM assignments AS a
        INNER JOIN dogs_info AS di
            ON a.dog_id = di.dog_id
        INNER JOIN rooms AS r
            ON a.room_id = r.room_id
        LEFT JOIN daily_attendance AS da
            ON da.dog_id = a.dog_id
            AND da.attendance_date = a.assignment_date
        WHERE a.assignment_date = %s
        ORDER BY r.room_id, di.dog_name
    """
    assignments_df = pd.read_sql(
        query,
        connection,
        params=(assignment_date,)
    )
    connection.close()
    return assignments_df


def load_assignment_record_dates():

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT record_date
            FROM daily_assignment_records
            ORDER BY record_date DESC
            """
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()


def load_assignment_record(assignment_date):

    connection = connect_database()
    query = """
        SELECT *
        FROM daily_assignment_records
        WHERE record_date = %s
    """
    record_df = pd.read_sql(
        query,
        connection,
        params=(assignment_date,)
    )
    connection.close()
    return record_df


# =============================================
# Bug Reports and Update Backlog
# =============================================

def create_bug_report(report):

    report_type = str(report.get("report_type") or "").strip()
    page_name = str(report.get("page_name") or "").strip()
    priority = str(report.get("priority") or "Medium").strip()
    title = str(report.get("title") or "").strip()
    description = str(report.get("description") or "").strip()

    if report_type not in {
        "Bug", "Feature Request", "Data Issue", "Assignment Rule Issue"
    }:
        raise ValueError("Select a valid report type.")
    if priority not in {"Low", "Medium", "High", "Urgent"}:
        raise ValueError("Select a valid priority.")
    if not page_name or len(page_name) > 50:
        raise ValueError("A valid page name is required.")
    if not title:
        raise ValueError("A short title is required.")
    if len(title) > 100:
        raise ValueError("The report title must be 100 characters or fewer.")
    if not description:
        raise ValueError("Describe the problem or request.")

    optional_values = [
        str(report.get(field) or "").strip() or None
        for field in (
            "expected_behavior",
            "actual_behavior",
            "related_dog",
            "related_room",
            "reporter_name"
        )
    ]
    expected, actual, related_dog, related_room, reporter_name = (
        optional_values
    )
    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO bug_reports
            (
                report_type,
                page_name,
                priority,
                title,
                description,
                expected_behavior,
                actual_behavior,
                related_dog,
                related_room,
                reporter_name,
                report_status,
                app_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'New', %s)
            """,
            (
                report_type,
                page_name,
                priority,
                title,
                description,
                expected,
                actual,
                related_dog,
                related_room,
                reporter_name,
                str(report.get("app_version") or "1.0.1")[:20]
            )
        )
        report_id = int(cursor.lastrowid)
        connection.commit()
        return report_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def load_bug_reports():

    connection = connect_database()

    try:
        return pd.read_sql(
            """
            SELECT *
            FROM bug_reports
            ORDER BY
                FIELD(priority, 'Urgent', 'High', 'Medium', 'Low'),
                FIELD(
                    report_status,
                    'New', 'Reviewing', 'In Progress', 'Fixed', 'Closed'
                ),
                created_at DESC
            """,
            connection
        )
    finally:
        connection.close()


def update_bug_report(report_id, report_status, resolution_notes=None):

    report_id = int(report_id)
    report_status = str(report_status).strip()
    resolution_notes = str(resolution_notes or "").strip() or None

    if report_status not in {
        "New", "Reviewing", "In Progress", "Fixed", "Closed"
    }:
        raise ValueError("Select a valid report status.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE bug_reports
            SET
                report_status = %s,
                resolution_notes = %s,
                updated_at = NOW(),
                resolved_at = CASE
                    WHEN %s IN ('Fixed', 'Closed')
                    THEN COALESCE(resolved_at, NOW())
                    ELSE NULL
                END
            WHERE report_id = %s
            """,
            (
                report_status,
                resolution_notes,
                report_status,
                report_id
            )
        )
        connection.commit()
        return cursor.rowcount == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def save_daily_assignments(assignments, update_reason=None):

    prepared = []

    for assignment in assignments:
        dog_id = int(assignment["dog_id"])
        room_id = int(assignment["room_id"])
        sibling_group_id = assignment.get("sibling_group_id")
        assignment_type = str(
            assignment.get("assignment_type") or "Automatic"
        ).strip()[:30]
        override_reason = str(
            assignment.get("override_reason") or ""
        ).strip() or None

        if sibling_group_id is not None:
            sibling_group_id = int(sibling_group_id)

        if override_reason and len(override_reason) > 200:
            raise ValueError(
                "Manual override reasons must be 200 characters or fewer."
            )

        prepared.append(
            (
                dog_id,
                room_id,
                sibling_group_id,
                assignment_type,
                override_reason
            )
        )

    if not prepared:
        raise ValueError("At least one assignment is required.")

    update_reason = str(update_reason or "").strip() or None

    if update_reason and len(update_reason) > 200:
        raise ValueError("Update reasons must be 200 characters or fewer.")

    connection = connect_database()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT revision_number
            FROM daily_assignment_records
            WHERE record_date = CURDATE()
            FOR UPDATE
            """
        )
        existing_record = cursor.fetchone()
        revision_number = (
            int(existing_record[0]) + 1
            if existing_record
            else 1
        )

        cursor.execute(
            "DELETE FROM assignments WHERE assignment_date = CURDATE()"
        )
        cursor.executemany(
            """
            INSERT INTO assignments
            (
                assignment_date,
                dog_id,
                room_id,
                sibling_group_id,
                assignment_type,
                override_reason,
                finalized_at
            )
            VALUES (CURDATE(), %s, %s, %s, %s, %s, NOW())
            """,
            prepared
        )
        cursor.execute(
            """
            INSERT INTO daily_assignment_records
            (
                record_date,
                status,
                revision_number,
                finalized_at,
                updated_at,
                update_reason
            )
            VALUES
            (
                CURDATE(),
                'Finalized',
                %s,
                NOW(),
                NOW(),
                %s
            )
            ON DUPLICATE KEY UPDATE
                status = 'Finalized',
                revision_number = VALUES(revision_number),
                updated_at = NOW(),
                update_reason = VALUES(update_reason)
            """,
            (revision_number, update_reason)
        )
        connection.commit()
        return {
            "saved_count": len(prepared),
            "revision_number": revision_number
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
