from datetime import date, datetime

import pandas as pd

from database import connect_database, sync_active_boarding_attendance


MEALS = ("Breakfast", "Lunch", "Dinner")


def load_boarding_care(care_date=None):
    care_date = care_date or date.today()
    sync_active_boarding_attendance()
    connection = connect_database()
    try:
        boarders = pd.read_sql(
            """
            SELECT bs.boarding_stay_id, bs.dog_id, di.dog_name,
                   di.sibling_group_id, bs.check_in_datetime,
                   bs.planned_checkout_datetime, bs.actual_checkout_datetime,
                   r.room_number, r.room_name, r.room_type,
                   COALESCE(p.breakfast_required, 1) breakfast_required,
                   COALESCE(p.lunch_required, 0) lunch_required,
                   COALESCE(p.dinner_required, 1) dinner_required,
                   COALESCE(p.breakfast_med_required, 0) breakfast_med_required,
                   COALESCE(p.lunch_med_required, 0) lunch_med_required,
                   COALESCE(p.dinner_med_required, 0) dinner_med_required,
                   COALESCE(p.feeding_tricks, '') feeding_tricks,
                   COALESCE(p.medication_tips, '') medication_tips,
                   COALESCE(p.allergy_status, 'Not recorded') allergy_status,
                   COALESCE(p.allergy_details, '') allergy_details,
                   COALESCE(p.food_label, '') food_label,
                   COALESCE(p.different_food_alert, 0) different_food_alert,
                   COALESCE(p.feeding_setup, 'Normal') feeding_setup
            FROM boarding_stays bs
            JOIN dogs_info di ON di.dog_id = bs.dog_id
            JOIN rooms r ON r.room_id = bs.assigned_room_id
            LEFT JOIN boarding_care_profiles p
              ON p.boarding_stay_id = bs.boarding_stay_id
            WHERE DATE(bs.check_in_datetime) <= %s
              AND DATE(COALESCE(bs.actual_checkout_datetime,
                                bs.planned_checkout_datetime)) >= %s
            ORDER BY r.room_id, di.dog_name
            """, connection, params=(care_date, care_date)
        )
        feedings = pd.read_sql(
            "SELECT * FROM boarding_feeding_records WHERE feeding_date = %s",
            connection, params=(care_date,)
        )
        medications = pd.read_sql(
            "SELECT * FROM boarding_medication_checks WHERE check_date = %s",
            connection, params=(care_date,)
        )
        return boarders, feedings, medications
    finally:
        connection.close()


def save_care_profile(stay_id, values):
    columns = (
        "breakfast_required", "lunch_required", "dinner_required",
        "breakfast_med_required", "lunch_med_required", "dinner_med_required",
        "feeding_tricks", "medication_tips", "allergy_status",
        "allergy_details", "food_label", "different_food_alert", "feeding_setup"
    )
    connection = connect_database()
    cursor = connection.cursor()
    try:
        placeholders = ", ".join(["%s"] * (len(columns) + 1))
        updates = ", ".join(f"{column}=VALUES({column})" for column in columns)
        cursor.execute(
            f"INSERT INTO boarding_care_profiles (boarding_stay_id, {', '.join(columns)}) "
            f"VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}",
            (int(stay_id),) + tuple(values[column] for column in columns)
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def place_food(stay_id, feeding_date, meal, initials):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO boarding_feeding_records
               (boarding_stay_id, feeding_date, meal, placed_by, placed_at)
               VALUES (%s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                 placed_by=IF(placed_at IS NULL, VALUES(placed_by), placed_by),
                 placed_at=IF(placed_at IS NULL, NOW(), placed_at)""",
            (int(stay_id), feeding_date, meal, initials)
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def pick_up_bowl(stay_id, feeding_date, meal, initials, appetite, note=""):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """UPDATE boarding_feeding_records SET picked_up_by=%s,
               picked_up_at=NOW(), appetite=%s, meal_note=%s
               WHERE boarding_stay_id=%s AND feeding_date=%s AND meal=%s
               AND placed_at IS NOT NULL AND picked_up_at IS NULL""",
            (initials, appetite, note or None, int(stay_id), feeding_date, meal)
        )
        if cursor.rowcount != 1:
            raise ValueError("This bowl was already updated or food was not placed.")
        connection.commit()
    finally:
        cursor.close(); connection.close()


def confirm_medication(stay_id, check_date, meal, initials, result, note=""):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO boarding_medication_checks
               (boarding_stay_id, check_date, meal, result, employee_initials,
                administration_note) VALUES (%s,%s,%s,%s,%s,%s)""",
            (int(stay_id), check_date, meal, result, initials, note or None)
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def add_boarding_note(stay_id, initials, note):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO boarding_care_notes (boarding_stay_id, employee_initials, note_text) VALUES (%s,%s,%s)",
            (int(stay_id), initials, note.strip())
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def load_stay_history(stay_id):
    connection = connect_database()
    try:
        feedings = pd.read_sql(
            "SELECT * FROM boarding_feeding_records WHERE boarding_stay_id=%s ORDER BY feeding_date DESC, meal",
            connection, params=(int(stay_id),)
        )
        meds = pd.read_sql(
            "SELECT * FROM boarding_medication_checks WHERE boarding_stay_id=%s ORDER BY check_date DESC, meal",
            connection, params=(int(stay_id),)
        )
        notes = pd.read_sql(
            "SELECT * FROM boarding_care_notes WHERE boarding_stay_id=%s ORDER BY created_at DESC",
            connection, params=(int(stay_id),)
        )
        return feedings, meds, notes
    finally:
        connection.close()
