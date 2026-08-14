import io
import runpy
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd


def native_value(value):

    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        return value.item()

    return value


def generate_assignment_draft():

    engine_path = Path(__file__).with_name("main.py")
    captured_report = io.StringIO()

    with redirect_stdout(captured_report):
        results = runpy.run_path(str(engine_path))

    dogs_df = results["dogs_df"]
    rooms_df = results["rooms_df"]
    dog_lookup = dogs_df.set_index("dog_id").to_dict("index")
    room_lookup = rooms_df.set_index("room_id").to_dict("index")
    assignments = []
    suggested_room_ids_by_dog = {}

    eligible_rooms_by_dog = results.get("eligible_rooms_by_dog", {})
    ranked_rooms_by_dog = results.get("ranked_rooms_by_dog", {})

    for dog_id, eligible_rooms in eligible_rooms_by_dog.items():
        ranked_rooms = ranked_rooms_by_dog.get(dog_id)

        if ranked_rooms is not None and not ranked_rooms.empty:
            eligible_rooms = pd.concat(
                [
                    ranked_rooms,
                    eligible_rooms[
                        ~eligible_rooms["room_id"].isin(
                            ranked_rooms["room_id"]
                        )
                    ]
                ],
                ignore_index=True
            )

        suggested_room_ids_by_dog[int(native_value(dog_id))] = [
            int(native_value(room_id))
            for room_id in eligible_rooms["room_id"].tolist()
        ]

    for assignment in results.get("final_assignments", []):
        dog_id = int(native_value(assignment["dog_id"]))
        room_id = int(native_value(assignment["room_id"]))
        dog = dog_lookup.get(dog_id, {})
        room = room_lookup.get(room_id, {})
        assignments.append(
            {
                "dog_id": dog_id,
                "dog_name": str(assignment["dog_name"]),
                "room_id": room_id,
                "room_number": str(assignment["room_number"]),
                "room_name": str(room.get("room_name") or ""),
                "room_type": str(assignment["room_type"]),
                "play_group": str(dog.get("play_group") or ""),
                "size_class": str(dog.get("size_class") or ""),
                "sibling_group_id": native_value(
                    dog.get("sibling_group_id")
                ),
                "visit_type": "Daycare",
                "assignment_type": str(
                    assignment.get("assignment_type") or "Automatic"
                ),
                "override_reason": None,
                "locked": False
            }
        )

    boarding_df = results.get("boarding", pd.DataFrame())

    for _, dog in boarding_df.iterrows():
        room_id = native_value(dog.get("assigned_room_id"))

        if room_id is None:
            continue

        room_id = int(room_id)
        room = room_lookup.get(room_id, {})
        assignments.append(
            {
                "dog_id": int(dog["dog_id"]),
                "dog_name": str(dog["dog_name"]),
                "room_id": room_id,
                "room_number": str(room.get("room_number") or room_id),
                "room_name": str(room.get("room_name") or ""),
                "room_type": str(room.get("room_type") or ""),
                "play_group": str(dog.get("play_group") or ""),
                "size_class": str(dog.get("size_class") or ""),
                "sibling_group_id": native_value(
                    dog.get("sibling_group_id")
                ),
                "visit_type": "Boarding",
                "assignment_type": "Boarding Reservation",
                "override_reason": None,
                "locked": True
            }
        )

    unassigned = []

    for item in results.get("unassigned_dogs", []):
        dog_id = int(native_value(item["dog_id"]))
        dog = dog_lookup.get(dog_id, {})
        unassigned.append(
            {
                "dog_id": dog_id,
                "dog_name": str(item["dog_name"]),
                "play_group": str(dog.get("play_group") or ""),
                "size_class": str(dog.get("size_class") or ""),
                "sibling_group_id": native_value(
                    dog.get("sibling_group_id")
                ),
                "visit_type": "Daycare",
                "reason": str(item.get("reason") or "No eligible room")
            }
        )

    return {
        "assignments": assignments,
        "unassigned": unassigned,
        "suggested_room_ids_by_dog": suggested_room_ids_by_dog,
        "report": captured_report.getvalue()
    }
