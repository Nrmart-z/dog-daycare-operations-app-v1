import pandas as pd


def room_section(room):

    room_type = str(room.get("room_type") or "").strip().lower()
    room_number = str(room.get("room_number") or "").strip()

    try:
        numeric_room = int(room_number)
    except ValueError:
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
        if numeric_room in {27, 28, 29, 34, 36, 38}:
            return "Back Hall"
        if 42 <= numeric_room <= 53:
            return "Kennels"
        if 54 <= numeric_room <= 58:
            return "Front Kennel"
        if numeric_room in {59, 60}:
            return "Crate Room"
    return None


def remaining_space_tables(assignments, rooms_df):

    occupied_room_ids = {
        int(assignment["room_id"])
        for assignment in assignments
        if assignment.get("room_id") is not None
    }
    open_rooms = rooms_df[
        pd.to_numeric(rooms_df["status"], errors="coerce").fillna(0) == 1
    ].copy()
    open_rooms["is_remaining"] = ~open_rooms["room_id"].astype(int).isin(
        occupied_room_ids
    )
    open_rooms["section"] = open_rooms.apply(
        lambda row: room_section(row.to_dict()),
        axis=1
    )

    crate_rows = []
    crate_rooms = open_rooms[
        open_rooms["room_type"].astype(str).str.strip().str.lower()
        == "crate"
    ].copy()
    crate_sizes = crate_rooms["size_group"].astype(str).str.strip().str.upper()

    for size in ("XS", "SM", "M", "L", "XL", "XXL"):
        matching = crate_rooms[crate_sizes == size]
        crate_rows.append(
            {
                "Crate Size": f"{size} Crates",
                "Remaining": int(matching["is_remaining"].sum()),
                "Open Total": len(matching)
            }
        )

    room_rows = []
    for section in (
        "Petite Suites",
        "Condo Suites",
        "Kennels",
        "Front Kennel",
        "Crate Room",
        "Floors",
        "Back Hall"
    ):
        matching = open_rooms[open_rooms["section"] == section]
        room_rows.append(
            {
                "Room Area": section,
                "Remaining": int(matching["is_remaining"].sum()),
                "Open Total": len(matching)
            }
        )

    return pd.DataFrame(crate_rows), pd.DataFrame(room_rows)
