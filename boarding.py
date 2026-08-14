import pandas as pd


KENNEL_SECTIONS = [
    [42, 43, 44, 45, 46],
    [47, 48, 49, 50, 51, 52, 53],
    [54, 55, 56, 57, 58],
    [59, 60]
]


def is_allowed(value):

    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def get_adjacent_kennels(room_number):

    try:
        room_number = int(room_number)
    except (TypeError, ValueError):
        return []

    for section in KENNEL_SECTIONS:

        if room_number not in section:
            continue

        position = section.index(room_number)
        adjacent = []

        if position > 0:
            adjacent.append(section[position - 1])

        if position < len(section) - 1:
            adjacent.append(section[position + 1])

        return adjacent

    return []


def get_fence_fighter_blocked_room_ids(dogs_df, rooms_df):

    if dogs_df.empty:
        return set()

    fence_fighter_room_ids = dogs_df.loc[
        (dogs_df["boarding_status"] == 1)
        & (
            pd.to_numeric(
                dogs_df["fence_fighter"], errors="coerce"
            ).fillna(0).astype(int) == 1
        ),
        "assigned_room_id"
    ].dropna().astype(int)

    blocked_numbers = set()

    for room_id in fence_fighter_room_ids:

        matching_rooms = rooms_df[
            rooms_df["room_id"].astype(int) == room_id
        ]

        if matching_rooms.empty:
            continue

        room = matching_rooms.iloc[0]

        if str(room["room_type"]).strip() == "Kennel":
            blocked_numbers.update(
                str(number)
                for number in get_adjacent_kennels(room["room_number"])
            )

    return set(
        rooms_df.loc[
            (rooms_df["room_type"] == "Kennel")
            & rooms_df["room_number"].astype(str).str.strip().isin(
                blocked_numbers
            ),
            "room_id"
        ].astype(int)
    )


def get_eligible_boarding_rooms(
    dog,
    rooms_df,
    occupied_room_ids=None,
    blocked_room_ids=None,
    allowed_occupied_room_ids=None
):

    occupied_room_ids = set(occupied_room_ids or set())
    blocked_room_ids = set(blocked_room_ids or set())
    allowed_occupied_room_ids = set(allowed_occupied_room_ids or set())

    room_status = pd.to_numeric(
        rooms_df["status"], errors="coerce"
    ).fillna(0)
    rooms = rooms_df[
        (room_status == 1)
        | rooms_df["room_id"].astype(int).isin(
            allowed_occupied_room_ids
        )
    ].copy()

    unavailable_room_ids = (
        occupied_room_ids | blocked_room_ids
    ) - allowed_occupied_room_ids

    rooms = rooms[
        ~rooms["room_id"].astype(int).isin(unavailable_room_ids)
    ].copy()

    # Crates are nap-time spaces only and are never boarding rooms.
    rooms = rooms[rooms["room_type"] != "Crate"].copy()

    if not is_allowed(dog["kennel_allowed"]):
        rooms = rooms[rooms["room_type"] != "Kennel"].copy()

    if is_allowed(dog["fence_jumpers"]):
        rooms = rooms[
            (rooms["room_type"] != "Kennel")
            | (pd.to_numeric(
                rooms["top_covered_kennel"], errors="coerce"
            ).fillna(0) > 0)
        ].copy()

    if not is_allowed(dog["suite_allowed"]):
        rooms = rooms[rooms["room_type"] != "Suite"].copy()

    if not is_allowed(dog["floor_allowed"]):
        rooms = rooms[rooms["room_type"] != "Floor"].copy()

    play_group = str(dog["play_group"]).strip()

    if play_group == "Small":
        rooms = rooms[
            ~(
                (rooms["room_type"] == "Floor")
                & (rooms["size_group"] == "Large")
            )
        ].copy()

    # Boarding suite access follows physical size, not daycare play group.
    # Small-size dogs may use Petite, Condo, or Back Hall suites.
    size_class = str(dog["size_class"]).strip()

    if size_class != "Small":
        room_numbers = pd.to_numeric(
            rooms["room_number"], errors="coerce"
        )
        petite_suite_mask = (
            (rooms["room_type"] == "Suite")
            & (
                (rooms["size_group"] == "Petite")
                | room_numbers.between(1, 10)
            )
        )
        rooms = rooms[
            ~petite_suite_mask
        ].copy()

    if is_allowed(dog["fence_fighter"]):
        occupied_kennel_numbers = set(
            rooms_df.loc[
                rooms_df["room_id"].astype(int).isin(occupied_room_ids)
                & (rooms_df["room_type"] == "Kennel"),
                "room_number"
            ].astype(str).str.strip()
        )

        rooms = rooms[
            rooms.apply(
                lambda room: (
                    room["room_type"] != "Kennel"
                    or not any(
                        str(number) in occupied_kennel_numbers
                        for number in get_adjacent_kennels(
                            room["room_number"]
                        )
                    )
                ),
                axis=1
            )
        ].copy()

    priority_column = {
        "Kennel": "kennel_priority",
        "Suite": "suite_priority",
        "Floor": "floor_priority"
    }

    rooms["dog_room_priority"] = rooms["room_type"].map(
        lambda room_type: pd.to_numeric(
            dog.get(priority_column.get(room_type, ""), 999),
            errors="coerce"
        )
    ).fillna(999)

    return rooms.sort_values(
        by=["dog_room_priority", "priority", "room_id"]
    ).reset_index(drop=True)


def get_shared_sibling_rooms(
    dogs,
    sibling_rule,
    rooms_df,
    occupied_room_ids=None,
    blocked_room_ids=None,
    allowed_occupied_room_ids=None
):

    shared_rooms = None

    for dog in dogs:
        dog_rooms = get_eligible_boarding_rooms(
            dog,
            rooms_df,
            occupied_room_ids=occupied_room_ids,
            blocked_room_ids=blocked_room_ids,
            allowed_occupied_room_ids=allowed_occupied_room_ids
        )

        if shared_rooms is None:
            shared_rooms = dog_rooms
        else:
            shared_rooms = shared_rooms[
                shared_rooms["room_id"].isin(dog_rooms["room_id"])
            ].copy()

    if shared_rooms is None:
        return rooms_df.iloc[0:0].copy()

    shared_priorities = {}

    for room_type, allowed_column, priority_column in (
        ("Suite", "shared_suite_allowed", "shared_suite_priority"),
        ("Floor", "shared_floor_allowed", "shared_floor_priority"),
        ("Kennel", "shared_kennel_allowed", "shared_kennel_priority")
    ):
        if is_allowed(sibling_rule[allowed_column]):
            shared_priorities[room_type] = int(
                sibling_rule[priority_column]
            )

    shared_rooms = shared_rooms[
        shared_rooms["shared_room_type"].isin(shared_priorities)
    ].copy()

    size_score = {"Small": 1, "Medium": 2, "Big": 3}
    scores = [
        size_score.get(str(dog["size_class"]).strip(), 3)
        for dog in dogs
    ]
    total_score = sum(scores)

    if len(dogs) >= 3:
        allowed_capacities = {"Large"}
    elif total_score == 2:
        allowed_capacities = {"Small", "Medium"}
    elif total_score in {3, 4, 5}:
        allowed_capacities = {"Medium", "Medium/Large", "Large"}
    else:
        allowed_capacities = {"Medium/Large", "Large"}

    shared_rooms = shared_rooms[
        shared_rooms["sibling_capacity"].isin(allowed_capacities)
    ].copy()

    shared_rooms["sibling_room_priority"] = (
        shared_rooms["shared_room_type"]
        .map(shared_priorities)
        .fillna(999)
    )

    capacity_rank = {
        "Small": 1,
        "Medium": 2,
        "Medium/Large": 2,
        "Large": 3
    }
    shared_rooms["capacity_rank"] = (
        shared_rooms["sibling_capacity"]
        .map(capacity_rank)
        .fillna(999)
    )

    return shared_rooms.sort_values(
        by=[
            "sibling_room_priority",
            "capacity_rank",
            "priority",
            "room_id"
        ]
    ).reset_index(drop=True)


def format_room_option(room):

    details = [
        f'{room["room_type"]} {room["room_number"]}',
        str(room["room_name"]),
        f'Size: {room["size_group"]}'
    ]

    return " | ".join(detail for detail in details if detail != "nan")
