from datetime import date, datetime, time, timedelta

import pandas as pd

from database import connect_database


OPEN_STATUSES = ("Open", "In Progress", "Needs Attention")


def _ensure_shift_trade_table(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS shift_trade_requests (
           trade_request_id INT NOT NULL AUTO_INCREMENT,
           requester_user_id INT NOT NULL, target_user_id INT NOT NULL,
           requester_shift_id INT NOT NULL, target_shift_id INT NOT NULL,
           request_note VARCHAR(500) NULL,
           status VARCHAR(20) NOT NULL DEFAULT 'Pending',
           created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
           reviewed_at DATETIME NULL,
           PRIMARY KEY (trade_request_id),
           KEY idx_trade_target_status (target_user_id, status, created_at),
           KEY idx_trade_requester (requester_user_id, created_at),
           CONSTRAINT fk_trade_requester FOREIGN KEY (requester_user_id) REFERENCES staff_users(user_id),
           CONSTRAINT fk_trade_target FOREIGN KEY (target_user_id) REFERENCES staff_users(user_id),
           CONSTRAINT fk_trade_requester_shift FOREIGN KEY (requester_shift_id) REFERENCES work_shifts(shift_id),
           CONSTRAINT fk_trade_target_shift FOREIGN KEY (target_shift_id) REFERENCES work_shifts(shift_id)
        )"""
    )


def _is_crew_backup_shift(shift):
    starts = shift["starts_at"].time().replace(second=0, microsecond=0)
    ends = shift["ends_at"].time().replace(second=0, microsecond=0)
    return shift["department"] == "Crew" and (starts, ends) in {
        (time(8, 0), time(11, 30)), (time(14, 0), time(17, 0))
    }


def _role_can_work_shift(role, shift):
    if role in ("Cross-Trained", "Boss", "Developer"):
        return True
    if role == "Crew":
        return shift["department"] == "Crew"
    if role == "Office":
        return shift["department"] == "Office" or _is_crew_backup_shift(shift)
    return False


def create_boarding_reservation(dog_id, arrival_date, departure_date,
                                pickup_period, room_id, notes, actor_id):
    if arrival_date < date.today():
        raise ValueError("Arrival date cannot be in the past.")
    if departure_date < arrival_date:
        raise ValueError("Departure date cannot be before arrival date.")
    if pickup_period not in ("AM", "PM"):
        raise ValueError("Pickup must be AM or PM.")
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO boarding_reservations
               (dog_id, arrival_date, departure_date, pickup_period, room_id,
                notes, created_by_user_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (int(dog_id), arrival_date, departure_date, pickup_period,
             int(room_id), notes.strip() or None, int(actor_id))
        )
        reservation_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'CREATE','boarding_reservation',%s,%s)""",
            (actor_id, str(reservation_id), f"Arrival {arrival_date}; departure {departure_date}")
        )
        connection.commit(); return reservation_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def load_boarding_reservations(start_date, end_date):
    connection = connect_database()
    try:
        return pd.read_sql(
            """SELECT br.*, d.dog_name, d.dog_breed, r.room_name, r.room_number
               FROM boarding_reservations br
               JOIN dogs_info d ON d.dog_id=br.dog_id
               JOIN rooms r ON r.room_id=br.room_id
               WHERE br.status='Planned'
                 AND (br.arrival_date BETWEEN %s AND %s
                      OR br.departure_date BETWEEN %s AND %s)
               ORDER BY br.arrival_date, d.dog_name""",
            connection, params=(start_date, end_date, start_date, end_date)
        )
    finally:
        connection.close()


def load_tasks(start_date=None, end_date=None, department=None, user_id=None):
    start_date = start_date or date.today()
    end_date = end_date or start_date
    clauses = ["DATE(t.due_at) BETWEEN %s AND %s"]
    params = [start_date, end_date]
    if department:
        clauses.append("t.department IN (%s, 'All')")
        params.append(department)
    if user_id:
        clauses.append("(t.assigned_user_id IS NULL OR t.assigned_user_id=%s)")
        params.append(int(user_id))
    connection = connect_database()
    try:
        return pd.read_sql(
            f"""SELECT t.*, d.dog_name, a.display_name assigned_to,
                       c.display_name completed_by
                FROM operations_tasks t
                LEFT JOIN dogs_info d ON d.dog_id=t.dog_id
                LEFT JOIN staff_users a ON a.user_id=t.assigned_user_id
                LEFT JOIN staff_users c ON c.user_id=t.completed_by_user_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.due_at,
                         FIELD(t.status,'Needs Attention','Open','In Progress','Completed','Skipped'),
                         FIELD(t.priority,'Urgent','High','Normal','Low')""",
            connection, params=tuple(params)
        )
    finally:
        connection.close()


def create_task(values, actor_id):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO operations_tasks
               (title, details, department, task_type, priority, due_at, dog_id,
                assigned_user_id, created_by_user_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (values["title"].strip(), values.get("details") or None,
             values["department"], values["task_type"], values["priority"],
             values["due_at"], values.get("dog_id"), values.get("assigned_user_id"),
             int(actor_id))
        )
        task_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'CREATE','task',%s,%s)""",
            (actor_id, str(task_id), values["title"].strip())
        )
        connection.commit(); return task_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def update_task_status(task_id, status, note, actor_id):
    allowed = ("Open", "In Progress", "Completed", "Skipped", "Refused", "Needs Attention")
    if status not in allowed:
        raise ValueError("Invalid task status.")
    completed = status in ("Completed", "Skipped", "Refused")
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """UPDATE operations_tasks SET status=%s, completion_note=%s,
                      completed_by_user_id=%s, completed_at=%s
               WHERE task_id=%s""",
            (status, note or None, actor_id if completed else None,
             datetime.now() if completed else None, int(task_id))
        )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'STATUS_CHANGE','task',%s,%s)""",
            (actor_id, str(task_id), f"Status: {status}. {note or ''}".strip())
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def load_users(active_only=True):
    connection = connect_database()
    try:
        where = "WHERE active=1" if active_only else ""
        return pd.read_sql(
            f"""SELECT user_id, username, first_name, last_name, display_name, role, active,
                       must_change_password, last_login_at, created_at
                FROM staff_users {where} ORDER BY active DESC, display_name""", connection
        )
    finally:
        connection.close()


def set_user_access(user_id, role, active, actor_id):
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT role FROM staff_users WHERE user_id=%s", (int(actor_id),))
        actor = cursor.fetchone()
        cursor.execute("SELECT role, active, display_name FROM staff_users WHERE user_id=%s", (int(user_id),))
        target = cursor.fetchone()
        if not target:
            raise ValueError("Account not found.")
        if actor and actor["role"] == "Boss" and target["role"] == "Developer":
            raise ValueError("Developer accounts are not available to Boss accounts.")
        if target["role"] == "Developer" and (role != "Developer" or not active):
            raise ValueError("Developer access cannot be deactivated or demoted from this screen.")
        if (target["role"] in ("Developer", "Boss")) != (role in ("Developer", "Boss")):
            raise ValueError("A Developer must make this role change and assign the correct PIN or password.")
        cursor.execute("UPDATE staff_users SET role=%s, active=%s WHERE user_id=%s", (role, int(active), int(user_id)))
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'ACCESS_CHANGE','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Role={role}; active={bool(active)}")
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def update_user_account(user_id, first_name, last_name, username, role, active,
                        new_credential, actor_id):
    from auth import hash_password, validate_credential

    user_id = int(user_id); actor_id = int(actor_id)
    first_name = first_name.strip(); last_name = last_name.strip()
    username = username.strip().lower()
    if not first_name or not last_name:
        raise ValueError("First name and last name are required.")
    if len(username) < 3:
        raise ValueError("Usernames must contain at least 3 characters.")
    if user_id == actor_id and (role != "Developer" or not active):
        raise ValueError("You cannot demote or deactivate the Developer account you are using.")
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT role FROM staff_users WHERE user_id=%s", (user_id,))
        target = cursor.fetchone()
        if not target:
            raise ValueError("Account not found.")
        if new_credential:
            validate_credential(new_credential, role)
        elif (target["role"] in ("Developer", "Boss")) != (role in ("Developer", "Boss")):
            raise ValueError("Enter a new credential when changing between a PIN role and password role.")
        display_name = f"{first_name} {last_name}"
        if new_credential:
            cursor.execute(
                """UPDATE staff_users SET first_name=%s, last_name=%s,
                          display_name=%s, username=%s, role=%s, active=%s,
                          password_hash=%s, must_change_password=0
                   WHERE user_id=%s""",
                (first_name, last_name, display_name, username, role, int(active),
                 hash_password(new_credential), user_id)
            )
        else:
            cursor.execute(
                """UPDATE staff_users SET first_name=%s, last_name=%s,
                          display_name=%s, username=%s, role=%s, active=%s
                   WHERE user_id=%s""",
                (first_name, last_name, display_name, username, role, int(active), user_id)
            )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'ACCOUNT_EDIT','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Updated {display_name}; role={role}; active={bool(active)}")
        )
        connection.commit()
        return {"first_name": first_name, "last_name": last_name,
                "display_name": display_name, "username": username,
                "role": role, "active": int(active)}
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def delete_user(user_id, actor_id):
    user_id = int(user_id); actor_id = int(actor_id)
    if user_id == actor_id:
        raise ValueError("You cannot delete the account you are currently using.")
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT username, display_name FROM staff_users WHERE user_id=%s", (user_id,))
        target = cursor.fetchone()
        if not target:
            raise ValueError("Account not found.")
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'DELETE','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Permanently deleted {target['display_name']} ({target['username']})")
        )
        cursor.execute("UPDATE operations_tasks SET assigned_user_id=NULL WHERE assigned_user_id=%s", (user_id,))
        cursor.execute("UPDATE operations_tasks SET completed_by_user_id=NULL WHERE completed_by_user_id=%s", (user_id,))
        cursor.execute("UPDATE operations_tasks SET created_by_user_id=%s WHERE created_by_user_id=%s", (actor_id, user_id))
        _ensure_shift_trade_table(cursor)
        cursor.execute(
            "DELETE FROM shift_trade_requests WHERE requester_user_id=%s OR target_user_id=%s",
            (user_id, user_id)
        )
        cursor.execute("DELETE FROM work_shifts WHERE user_id=%s", (user_id,))
        cursor.execute("UPDATE work_shifts SET created_by_user_id=%s WHERE created_by_user_id=%s", (actor_id, user_id))
        cursor.execute("DELETE FROM employee_normal_schedules WHERE user_id=%s", (user_id,))
        cursor.execute("UPDATE employee_normal_schedules SET updated_by_user_id=%s WHERE updated_by_user_id=%s", (actor_id, user_id))
        cursor.execute("UPDATE schedule_holidays SET created_by_user_id=%s WHERE created_by_user_id=%s", (actor_id, user_id))
        cursor.execute("UPDATE time_off_requests SET reviewed_by_user_id=NULL WHERE reviewed_by_user_id=%s", (user_id,))
        cursor.execute("DELETE FROM time_off_requests WHERE user_id=%s", (user_id,))
        cursor.execute("UPDATE operations_audit_log SET user_id=NULL WHERE user_id=%s", (user_id,))
        cursor.execute("DELETE FROM notification_preferences WHERE user_id=%s", (user_id,))
        cursor.execute("DELETE FROM staff_users WHERE user_id=%s", (user_id,))
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def load_shifts(start_date, end_date, user_id=None):
    connection = connect_database()
    try:
        user_clause = "AND s.user_id=%s" if user_id else ""
        params = (start_date, end_date, int(user_id)) if user_id else (start_date, end_date)
        return pd.read_sql(
            f"""SELECT s.*, u.display_name, u.role
                FROM work_shifts s JOIN staff_users u ON u.user_id=s.user_id
                WHERE DATE(s.starts_at) BETWEEN %s AND %s
                  AND u.role <> 'Developer' {user_clause}
                ORDER BY s.starts_at, s.ends_at, u.display_name""", connection, params=params
        )
    finally:
        connection.close()


def load_holidays(start_date, end_date):
    connection = connect_database()
    try:
        return pd.read_sql(
            """SELECT holiday_date, holiday_name FROM schedule_holidays
               WHERE holiday_date BETWEEN %s AND %s ORDER BY holiday_date""",
            connection, params=(start_date, end_date)
        )
    finally:
        connection.close()


def load_normal_schedule(user_id=None):
    connection = connect_database()
    try:
        clause = "WHERE n.user_id=%s" if user_id else ""
        params = (int(user_id),) if user_id else None
        return pd.read_sql(
            f"""SELECT n.*, u.display_name, u.role
                FROM employee_normal_schedules n
                JOIN staff_users u ON u.user_id=n.user_id
                {clause} ORDER BY n.user_id, n.weekday_number, n.period""",
            connection, params=params
        )
    finally:
        connection.close()


def save_normal_schedule(user_id, selections, actor_id):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM employee_normal_schedules WHERE user_id=%s", (int(user_id),))
        for weekday_number, period, shift_label in selections:
            cursor.execute(
                """INSERT INTO employee_normal_schedules
                   (user_id, weekday_number, period, shift_label, updated_by_user_id)
                   VALUES (%s,%s,%s,%s,%s)""",
                (int(user_id), int(weekday_number), period, shift_label, int(actor_id))
            )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'NORMAL_SCHEDULE','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Saved {len(selections)} normal shift(s)")
        )
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def clear_generated_shifts(user_id, start_date, end_date, actor_id):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """DELETE FROM work_shifts
               WHERE user_id=%s AND DATE(starts_at) BETWEEN %s AND %s
                 AND notes='Auto-generated from normal schedule'""",
            (int(user_id), start_date, end_date)
        )
        removed = cursor.rowcount
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'SCHEDULE_SYNC','staff_user',%s,%s)""",
            (actor_id, str(user_id), f"Cleared {removed} generated shifts for resync")
        )
        connection.commit(); return removed
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def is_schedule_holiday(holiday_date):
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT holiday_name FROM schedule_holidays WHERE holiday_date=%s",
            (holiday_date,)
        )
        row = cursor.fetchone()
        return (True, row[0] or "Holiday") if row else (False, "")
    finally:
        cursor.close(); connection.close()


def set_schedule_holiday(holiday_date, enabled, holiday_name, actor_id):
    connection = connect_database(); cursor = connection.cursor()
    try:
        if enabled:
            cursor.execute(
                """INSERT INTO schedule_holidays
                   (holiday_date, holiday_name, created_by_user_id)
                   VALUES (%s,%s,%s)
                   ON DUPLICATE KEY UPDATE holiday_name=VALUES(holiday_name),
                     created_by_user_id=VALUES(created_by_user_id)""",
                (holiday_date, holiday_name.strip() or "Holiday", int(actor_id))
            )
            detail = f"Holiday hours enabled: {holiday_name.strip() or 'Holiday'}"
        else:
            cursor.execute("DELETE FROM schedule_holidays WHERE holiday_date=%s", (holiday_date,))
            detail = "Holiday hours removed"
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'HOLIDAY_SETTING','schedule_date',%s,%s)""",
            (actor_id, str(holiday_date), detail)
        )
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def create_shift(user_id, starts_at, ends_at, department, notes, actor_id):
    if ends_at <= starts_at:
        raise ValueError("Shift end must be after its start.")
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO work_shifts
               (user_id, starts_at, ends_at, department, notes, created_by_user_id)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (int(user_id), starts_at, ends_at, department, notes or None, int(actor_id))
        )
        shift_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'CREATE','shift',%s,%s)""",
            (actor_id, str(shift_id), f"Shift {starts_at} - {ends_at}")
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()


def create_shifts_batch(assignments, actor_id):
    """Create validated shift assignments in one transaction."""
    connection = connect_database(); cursor = connection.cursor()
    try:
        for assignment in assignments:
            period = "AM" if assignment["starts_at"].hour < 12 else "PM"
            cursor.execute(
                """SELECT COUNT(*) FROM time_off_requests
                   WHERE user_id=%s AND status='Approved'
                     AND %s BETWEEN start_date AND end_date
                     AND period IN (%s, 'Both')""",
                (int(assignment["user_id"]), assignment["starts_at"].date(), period)
            )
            if int(cursor.fetchone()[0]):
                raise ValueError(
                    f"{assignment['display_name']} has approved time off for that {period} shift."
                )
            cursor.execute(
                """SELECT COUNT(*) FROM work_shifts
                   WHERE user_id=%s AND DATE(starts_at)=%s
                     AND ((HOUR(starts_at) < 12 AND %s < 12)
                          OR (HOUR(starts_at) >= 12 AND %s >= 12))""",
                (int(assignment["user_id"]), assignment["starts_at"].date(),
                 assignment["starts_at"].hour, assignment["starts_at"].hour)
            )
            if int(cursor.fetchone()[0]):
                raise ValueError(f"{assignment['display_name']} already has a shift in that period.")
        for assignment in assignments:
            cursor.execute(
                """INSERT INTO work_shifts
                   (user_id, starts_at, ends_at, department, notes, created_by_user_id)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (int(assignment["user_id"]), assignment["starts_at"],
                 assignment["ends_at"], assignment["department"],
                 assignment.get("notes") or None, int(actor_id))
            )
            shift_id = cursor.lastrowid
            cursor.execute(
                """INSERT INTO operations_audit_log
                   (user_id, action, entity_type, entity_id, details)
                   VALUES (%s,'CREATE','shift',%s,%s)""",
                (actor_id, str(shift_id),
                 f"Shift {assignment['starts_at']} - {assignment['ends_at']}")
            )
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def remove_shift(shift_id, reason, actor_id):
    if not reason.strip():
        raise ValueError("Enter a reason such as called out, time off, or shift switch.")
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT s.shift_id, s.starts_at, u.display_name
               FROM work_shifts s JOIN staff_users u ON u.user_id=s.user_id
               WHERE s.shift_id=%s""", (int(shift_id),)
        )
        shift = cursor.fetchone()
        if not shift:
            raise ValueError("Shift not found.")
        _ensure_shift_trade_table(cursor)
        cursor.execute(
            "DELETE FROM shift_trade_requests WHERE requester_shift_id=%s OR target_shift_id=%s",
            (int(shift_id), int(shift_id))
        )
        cursor.execute("DELETE FROM work_shifts WHERE shift_id=%s", (int(shift_id),))
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'SHIFT_REMOVED','shift',%s,%s)""",
            (actor_id, str(shift_id),
             f"{shift['display_name']} {shift['starts_at']}: {reason.strip()}")
        )
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def create_shift_trade_request(requester_user_id, requester_shift_id,
                               target_shift_id, note=""):
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        _ensure_shift_trade_table(cursor)
        cursor.execute(
            """SELECT s.*, u.role, u.display_name FROM work_shifts s
               JOIN staff_users u ON u.user_id=s.user_id
               WHERE s.shift_id IN (%s,%s) FOR UPDATE""",
            (int(requester_shift_id), int(target_shift_id))
        )
        rows = {int(row["shift_id"]): row for row in cursor.fetchall()}
        own = rows.get(int(requester_shift_id)); target = rows.get(int(target_shift_id))
        if not own or not target:
            raise ValueError("One of those shifts is no longer available.")
        if int(own["user_id"]) != int(requester_user_id):
            raise ValueError("You can only offer one of your own shifts.")
        if int(target["user_id"]) == int(requester_user_id):
            raise ValueError("Choose another employee's shift.")
        if own["starts_at"] < datetime.now() or target["starts_at"] < datetime.now():
            raise ValueError("Past shifts cannot be switched.")
        if not _role_can_work_shift(target["role"], own):
            raise ValueError(f"{target['display_name']} is not qualified for your shift.")
        if not _role_can_work_shift(own["role"], target):
            raise ValueError("You are not qualified for the requested shift.")
        cursor.execute(
            """SELECT COUNT(*) total FROM shift_trade_requests
               WHERE status='Pending' AND (requester_shift_id IN (%s,%s)
               OR target_shift_id IN (%s,%s))""",
            (own["shift_id"], target["shift_id"], own["shift_id"], target["shift_id"])
        )
        if int(cursor.fetchone()["total"]):
            raise ValueError("One of these shifts already has a pending switch request.")
        cursor.execute(
            """INSERT INTO shift_trade_requests
               (requester_user_id, target_user_id, requester_shift_id,
                target_shift_id, request_note)
               VALUES (%s,%s,%s,%s,%s)""",
            (int(requester_user_id), int(target["user_id"]), own["shift_id"],
             target["shift_id"], note.strip() or None)
        )
        request_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'SHIFT_TRADE_REQUEST','shift_trade',%s,%s)""",
            (requester_user_id, str(request_id),
             f"Requested trade with {target['display_name']}")
        )
        connection.commit(); return request_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def load_shift_trade_requests(user_id):
    connection = connect_database()
    try:
        cursor = connection.cursor(); _ensure_shift_trade_table(cursor)
        connection.commit(); cursor.close()
        return pd.read_sql(
            """SELECT tr.*, requester.display_name requester_name,
                      target.display_name target_name,
                      offered.starts_at offered_starts_at,
                      offered.ends_at offered_ends_at,
                      offered.department offered_department,
                      requested.starts_at requested_starts_at,
                      requested.ends_at requested_ends_at,
                      requested.department requested_department
               FROM shift_trade_requests tr
               JOIN staff_users requester ON requester.user_id=tr.requester_user_id
               JOIN staff_users target ON target.user_id=tr.target_user_id
               JOIN work_shifts offered ON offered.shift_id=tr.requester_shift_id
               JOIN work_shifts requested ON requested.shift_id=tr.target_shift_id
               WHERE tr.requester_user_id=%s OR tr.target_user_id=%s
               ORDER BY (tr.status='Pending') DESC, tr.created_at DESC""",
            connection, params=(int(user_id), int(user_id))
        )
    finally:
        connection.close()


def review_shift_trade_request(request_id, target_user_id, decision):
    if decision not in ("Accepted", "Denied"):
        raise ValueError("Choose Accept or Deny.")
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        _ensure_shift_trade_table(cursor)
        cursor.execute(
            "SELECT * FROM shift_trade_requests WHERE trade_request_id=%s FOR UPDATE",
            (int(request_id),)
        )
        request = cursor.fetchone()
        if not request or request["status"] != "Pending":
            raise ValueError("This switch request is no longer pending.")
        if int(request["target_user_id"]) != int(target_user_id):
            raise ValueError("Only the requested employee can answer this switch.")
        if decision == "Accepted":
            cursor.execute(
                "SELECT * FROM work_shifts WHERE shift_id IN (%s,%s) FOR UPDATE",
                (request["requester_shift_id"], request["target_shift_id"])
            )
            shifts = {int(row["shift_id"]): row for row in cursor.fetchall()}
            offered = shifts.get(int(request["requester_shift_id"]))
            requested = shifts.get(int(request["target_shift_id"]))
            if (not offered or not requested
                    or int(offered["user_id"]) != int(request["requester_user_id"])
                    or int(requested["user_id"]) != int(request["target_user_id"])):
                raise ValueError("The schedule changed, so this request can no longer be accepted.")
            for receiving_user, shift in (
                (request["target_user_id"], offered),
                (request["requester_user_id"], requested),
            ):
                cursor.execute(
                    """SELECT COUNT(*) total FROM work_shifts
                       WHERE user_id=%s AND shift_id NOT IN (%s,%s)
                         AND starts_at < %s AND ends_at > %s""",
                    (receiving_user, offered["shift_id"], requested["shift_id"],
                     shift["ends_at"], shift["starts_at"])
                )
                if int(cursor.fetchone()["total"]):
                    raise ValueError("The switch would create an overlapping shift.")
            cursor.execute("UPDATE work_shifts SET user_id=%s WHERE shift_id=%s",
                           (request["target_user_id"], offered["shift_id"]))
            cursor.execute("UPDATE work_shifts SET user_id=%s WHERE shift_id=%s",
                           (request["requester_user_id"], requested["shift_id"]))
        cursor.execute(
            """UPDATE shift_trade_requests SET status=%s, reviewed_at=NOW()
               WHERE trade_request_id=%s""", (decision, int(request_id))
        )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'SHIFT_TRADE_REVIEW','shift_trade',%s,%s)""",
            (target_user_id, str(request_id), decision)
        )
        connection.commit()
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def create_time_off_request(user_id, start_date, end_date, period, note):
    if end_date < start_date:
        raise ValueError("The ending date cannot be before the starting date.")
    if start_date < date.today():
        raise ValueError("Time-off requests cannot begin in the past.")
    if period not in ("AM", "PM", "Both"):
        raise ValueError("Choose AM, PM, or Both.")
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO time_off_requests
               (user_id, start_date, end_date, period, request_note)
               VALUES (%s,%s,%s,%s,%s)""",
            (int(user_id), start_date, end_date, period, note.strip() or None)
        )
        request_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'TIME_OFF_REQUEST','time_off',%s,%s)""",
            (user_id, str(request_id), f"{start_date} through {end_date}; {period}")
        )
        connection.commit(); return request_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def _ensure_time_off_days_table(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS time_off_request_days (
           request_day_id INT NOT NULL AUTO_INCREMENT,
           request_id INT NOT NULL, request_date DATE NOT NULL,
           period VARCHAR(10) NOT NULL,
           PRIMARY KEY (request_day_id),
           UNIQUE KEY uq_time_off_request_day (request_id, request_date),
           KEY idx_time_off_day_date (request_date),
           CONSTRAINT fk_time_off_day_request FOREIGN KEY (request_id)
             REFERENCES time_off_requests(request_id) ON DELETE CASCADE
        )"""
    )


def create_detailed_time_off_request(user_id, day_periods, note):
    if not day_periods:
        raise ValueError("Choose at least one day.")
    normalized = sorted((request_date, period) for request_date, period in day_periods.items())
    if normalized[0][0] < date.today():
        raise ValueError("Time-off requests cannot begin in the past.")
    if any(period not in ("AM", "PM", "Both") for _, period in normalized):
        raise ValueError("Choose AM, PM, or Both for every day.")
    connection = connect_database(); cursor = connection.cursor()
    try:
        _ensure_time_off_days_table(cursor)
        start_date, end_date = normalized[0][0], normalized[-1][0]
        summary_period = normalized[0][1] if len({p for _, p in normalized}) == 1 else "Varies"
        cursor.execute(
            """INSERT INTO time_off_requests
               (user_id, start_date, end_date, period, request_note)
               VALUES (%s,%s,%s,%s,%s)""",
            (int(user_id), start_date, end_date, summary_period, note.strip() or None)
        )
        request_id = cursor.lastrowid
        cursor.executemany(
            """INSERT INTO time_off_request_days (request_id, request_date, period)
               VALUES (%s,%s,%s)""",
            [(request_id, request_date, period) for request_date, period in normalized]
        )
        detail = ", ".join(f"{day:%m/%d/%Y} {period}" for day, period in normalized)
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'TIME_OFF_REQUEST','time_off',%s,%s)""",
            (user_id, str(request_id), detail)
        )
        connection.commit(); return request_id
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def load_time_off_request_days(request_id):
    connection = connect_database()
    try:
        cursor = connection.cursor(); _ensure_time_off_days_table(cursor); connection.commit(); cursor.close()
        return pd.read_sql(
            """SELECT request_date, period FROM time_off_request_days
               WHERE request_id=%s ORDER BY request_date""",
            connection, params=(int(request_id),)
        )
    finally:
        connection.close()


def load_time_off_requests(user_id=None, status=None):
    clauses = []; params = []
    if user_id is not None:
        clauses.append("r.user_id=%s"); params.append(int(user_id))
    if status:
        clauses.append("r.status=%s"); params.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    connection = connect_database()
    try:
        return pd.read_sql(
            f"""SELECT r.*, u.display_name,
                       reviewer.display_name reviewed_by
                FROM time_off_requests r
                JOIN staff_users u ON u.user_id=r.user_id
                LEFT JOIN staff_users reviewer ON reviewer.user_id=r.reviewed_by_user_id
                {where}
                ORDER BY FIELD(r.status,'Pending','Approved','Denied'),
                         r.start_date, r.created_at""",
            connection, params=tuple(params) if params else None
        )
    finally:
        connection.close()


def pending_time_off_count():
    connection = connect_database(); cursor = connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM time_off_requests WHERE status='Pending'")
        return int(cursor.fetchone()[0])
    finally:
        cursor.close(); connection.close()


def review_time_off_request(request_id, approved, review_note, boss_user_id):
    connection = connect_database(); cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM time_off_requests
               WHERE request_id=%s AND status='Pending' FOR UPDATE""",
            (int(request_id),)
        )
        request = cursor.fetchone()
        if not request:
            raise ValueError("This request was already reviewed or no longer exists.")
        status = "Approved" if approved else "Denied"
        removed = 0
        if approved:
            _ensure_time_off_days_table(cursor)
            cursor.execute(
                "SELECT request_date, period FROM time_off_request_days WHERE request_id=%s",
                (int(request_id),)
            )
            request_days = cursor.fetchall()
            if request_days:
                for request_day in request_days:
                    period_clause = ""
                    if request_day["period"] == "AM":
                        period_clause = "AND HOUR(starts_at) < 12"
                    elif request_day["period"] == "PM":
                        period_clause = "AND HOUR(starts_at) >= 12"
                    cursor.execute(
                        f"""DELETE FROM work_shifts WHERE user_id=%s
                            AND DATE(starts_at)=%s {period_clause}""",
                        (request["user_id"], request_day["request_date"])
                    )
                    removed += cursor.rowcount
            else:
                period_clause = ""
                if request["period"] == "AM": period_clause = "AND HOUR(starts_at) < 12"
                elif request["period"] == "PM": period_clause = "AND HOUR(starts_at) >= 12"
                cursor.execute(
                    f"""DELETE FROM work_shifts WHERE user_id=%s
                        AND DATE(starts_at) BETWEEN %s AND %s {period_clause}""",
                    (request["user_id"], request["start_date"], request["end_date"])
                )
                removed = cursor.rowcount
        cursor.execute(
            """UPDATE time_off_requests SET status=%s, reviewed_by_user_id=%s,
                      review_note=%s, reviewed_at=NOW() WHERE request_id=%s""",
            (status, int(boss_user_id), review_note.strip() or None, int(request_id))
        )
        cursor.execute(
            """INSERT INTO operations_audit_log
               (user_id, action, entity_type, entity_id, details)
               VALUES (%s,'TIME_OFF_REVIEW','time_off',%s,%s)""",
            (boss_user_id, str(request_id), f"{status}; removed {removed} shift(s)")
        )
        connection.commit(); return removed
    except Exception:
        connection.rollback(); raise
    finally:
        cursor.close(); connection.close()


def load_day_summary(summary_date):
    connection = connect_database()
    try:
        arrivals = pd.read_sql(
            """SELECT d.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(d.dog_breed, ''), 'Not recorded') AS Breed,
                      COALESCE(NULLIF(r.room_name, ''),
                               CONCAT('Room ', r.room_number),
                               'Unassigned') AS `Room Name`
               FROM boarding_stays bs JOIN dogs_info d ON d.dog_id=bs.dog_id
               LEFT JOIN rooms r ON r.room_id=bs.assigned_room_id
               WHERE DATE(bs.check_in_datetime)=%s
                 AND bs.stay_status <> 'Cancelled'
               ORDER BY bs.check_in_datetime, d.dog_name""",
            connection, params=(summary_date,)
        )
        departures = pd.read_sql(
            """SELECT d.dog_name AS `Dog Name`,
                      COALESCE(NULLIF(d.dog_breed, ''), 'Not recorded') AS Breed,
                      COALESCE(NULLIF(r.room_name, ''),
                               CONCAT('Room ', r.room_number),
                               'Unassigned') AS `Room Name`,
                      CASE WHEN HOUR(bs.planned_checkout_datetime) < 12
                           THEN 'AM' ELSE 'PM' END AS `AM or PM`
               FROM boarding_stays bs JOIN dogs_info d ON d.dog_id=bs.dog_id
               LEFT JOIN rooms r ON r.room_id=bs.assigned_room_id
               WHERE DATE(bs.planned_checkout_datetime)=%s AND bs.stay_status <> 'Cancelled'
               ORDER BY bs.planned_checkout_datetime, d.dog_name""",
            connection, params=(summary_date,)
        )
        planned = pd.read_sql(
            """SELECT br.arrival_date, br.departure_date, br.pickup_period,
                      d.dog_name, d.dog_breed, r.room_name, r.room_number
               FROM boarding_reservations br
               JOIN dogs_info d ON d.dog_id=br.dog_id
               JOIN rooms r ON r.room_id=br.room_id
               WHERE br.status='Planned'
                 AND (br.arrival_date=%s OR br.departure_date=%s)""",
            connection, params=(summary_date, summary_date)
        )
        if not planned.empty:
            room_names = planned.apply(
                lambda row: row["room_name"] or f"Room {row['room_number']}", axis=1
            )
            planned_arrivals = planned[planned.arrival_date == summary_date].copy()
            if not planned_arrivals.empty:
                planned_arrivals["Room Name"] = room_names.loc[planned_arrivals.index]
                planned_arrivals = planned_arrivals.rename(columns={"dog_name": "Dog Name", "dog_breed": "Breed"})
                arrivals = pd.concat([arrivals, planned_arrivals[["Dog Name", "Breed", "Room Name"]]], ignore_index=True).drop_duplicates("Dog Name")
            planned_departures = planned[planned.departure_date == summary_date].copy()
            if not planned_departures.empty:
                planned_departures["Room Name"] = room_names.loc[planned_departures.index]
                planned_departures = planned_departures.rename(columns={"dog_name": "Dog Name", "dog_breed": "Breed", "pickup_period": "AM or PM"})
                departures = pd.concat([departures, planned_departures[["Dog Name", "Breed", "Room Name", "AM or PM"]]], ignore_index=True).drop_duplicates("Dog Name")
        return arrivals, departures
    finally:
        connection.close()


def load_audit(limit=100):
    connection = connect_database()
    try:
        return pd.read_sql(
            """SELECT a.created_at, COALESCE(u.display_name,'System') employee,
                      a.action, a.entity_type, a.entity_id, a.details
               FROM operations_audit_log a LEFT JOIN staff_users u ON u.user_id=a.user_id
               ORDER BY a.created_at DESC LIMIT %s""", connection, params=(int(limit),)
        )
    finally:
        connection.close()
