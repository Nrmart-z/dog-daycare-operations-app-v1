import pandas as pd
from database import load_dogs, load_rooms, load_sibling_group

# =====================================================
# LOAD DATABASE TABLES
# =====================================================

dogs_df             = load_dogs()
rooms_df            = load_rooms()
sibling_group_df    = load_sibling_group()


#============================================================
#  Convert permission columns to integers
# This prevents values such as "0" from being treated as True
#=============================================================
boolean_columns = [
    "boarding_status",
    "crate_allowed",
    "larger_crate_allowed",
    "kennel_allowed",
    "suite_allowed",
    "floor_allowed",
    "fence_fighter"
]
dogs_df["assigned_room_id"] = pd.to_numeric(
    dogs_df["assigned_room_id"],
    errors="coerce"
).astype("Int64")

for column in boolean_columns:
    dogs_df[column] = pd.to_numeric(
        dogs_df[column],
        errors="coerce"
    ).fillna(0).astype(int)

# Split dogs by boarding status
boarding = dogs_df[
    dogs_df["boarding_status"] == 1
].copy()

daycare = dogs_df[
    dogs_df["boarding_status"] == 0
].copy()

# Temporary datatype test
print(dogs_df["kennel_allowed"].unique())
print(dogs_df["kennel_allowed"].dtype)

# Optional play-group DataFrames
petite = dogs_df[
    dogs_df["play_group"] == "Small"
].copy()

big_dogs = dogs_df[
    dogs_df["play_group"] == "Big"
].copy()

separates = dogs_df[
    dogs_df["play_group"] == "Separate"
].copy()


# =====================================================
# CONVERT DOG BOOLEAN COLUMNS/
# =====================================================

dog_boolean_columns = [
    "boarding_status",
    "crate_allowed",
    "larger_crate_allowed",
    "kennel_allowed",
    "suite_allowed",
    "floor_allowed",
    "fence_fighter",
    "fence_jumpers",
]

for column in dog_boolean_columns:

    dogs_df[column] = pd.to_numeric(
        dogs_df[column],
        errors="coerce"
    ).fillna(0).astype(int)

# =====================================================
# CONVERT TOP COVERED BOOLEAN COLUMN
# =====================================================

room_boolean_columns = [
    "top_covered_kennel"
]

for column in room_boolean_columns:

    rooms_df[column] = pd.to_numeric(
        rooms_df[column],
        errors="coerce"
    ).fillna(0).astype(int)

# =====================================================
# CONVERT SIBLING BOOLEAN COLUMNS
# =====================================================

sibling_boolean_columns = [
    "keep_together",
    "shared_suite_allowed",
    "shared_floor_allowed",
    "shared_kennel_allowed"
]

for column in sibling_boolean_columns:

    sibling_group_df[column] = pd.to_numeric(
        sibling_group_df[column],
        errors="coerce"
    ).fillna(0).astype(int)


# =====================================================
# CRATE SIZE PROGRESSION
# Used for dogs allowed one crate size larger
# =====================================================

next_crate_size = {
    "XS": "SM",
    "SM": "M",
    "M": "L",
    "L": "XL",
    "XL": "XXL"
}

# =====================================================
# CREATE WORKING ROOM LIST
# =====================================================

available_rooms = rooms_df.copy()

# =====================================================
# RESERVE BOARDING ROOMS
# Marks occupied boarding rooms as unavailable
# =====================================================

for index, dog in boarding.iterrows():

    print(
        dog["dog_name"],
        "is boarding in room",
        dog["assigned_room_id"]
    )

    available_rooms.loc[
        available_rooms["room_id"] == dog["assigned_room_id"],
        "status"
    ] = 0

# =====================================================
# DAYCARE ROOM ASSIGNMENT
# =====================================================
eligible_rooms_by_dog = {}

for index, dog in daycare.iterrows():

    print("\n" + "=" * 60)
    print(f'Processing {dog["dog_name"]}')

    # -------------------------------------------------
    # STEP 1 - START WITH AVAILABLE ROOMS
    # -------------------------------------------------

    eligible_rooms = available_rooms[
        available_rooms["status"] == 1
    ].copy()

    # -------------------------------------------------
    # STEP 2 - DETERMINE PLAY GROUP
    # -------------------------------------------------

    if dog["play_group"] == "Small":
        print(f'{dog["dog_name"]} goes to the SMALL group.')

    elif dog["play_group"] == "Big":
        print(f'{dog["dog_name"]} goes to the BIG group.')

    elif dog["play_group"] == "Separate":
        print(f'{dog["dog_name"]} must stay SEPARATE.')

    # -------------------------------------------------
    # STEP 3 - FILTER CRATE ELIGIBILITY
    # -------------------------------------------------

    print(
        dog["dog_name"],
        "crate_allowed:",
        dog["crate_allowed"],
        "crate_size:",
        dog["crate_size"]
    )

    if not dog["crate_allowed"]:

        # Remove every crate
        eligible_rooms = eligible_rooms[
            eligible_rooms["room_type"] != "Crate"
        ].copy()

        allowed_crate_sizes = []

    else:

        # Keep all non-crate rooms
        non_crate_rooms = eligible_rooms[
            eligible_rooms["room_type"] != "Crate"
        ].copy()

        # Start with the dog's normal crate size
        allowed_crate_sizes = [
            dog["crate_size"]
        ]

        # Add one larger crate size when permitted
        if dog["larger_crate_allowed"]:

            larger_size = next_crate_size.get(
                dog["crate_size"]
            )

            if larger_size is not None:
                allowed_crate_sizes.append(
                    larger_size
                )

        # Keep only crates matching an allowed size
        matching_crates = eligible_rooms[
            (eligible_rooms["room_type"] == "Crate")
            &
            (
                eligible_rooms["size_group"].isin(
                    allowed_crate_sizes
                )
            )
        ].copy()

        # Recombine legal crates with all non-crate rooms
        eligible_rooms = pd.concat(
            [
                non_crate_rooms,
                matching_crates
            ],
            ignore_index=True
        )

    

    # -------------------------------------------------
    # STEP 4A - FILTER KENNEL ELIGIBILITY
    # -------------------------------------------------

    print(
        dog["dog_name"],
        "kennel_allowed:",
        dog["kennel_allowed"],
        type(dog["kennel_allowed"])
    )

    if not dog["kennel_allowed"]:

        # Remove every kennel
        eligible_rooms = eligible_rooms[
            eligible_rooms["room_type"] != "Kennel"
        ].copy()


    

    # -------------------------------------------------
    #   STEP 4B - FILTER KENNELS FOR FENCE JUMPERS
    # -------------------------------------------------

    if dog["fence_jumpers"] == 1:

        eligible_rooms = eligible_rooms[
        (
            eligible_rooms["room_type"] != "Kennel"
        )
        |
        (
            eligible_rooms["top_covered_kennel"] == 1
        )
    ].copy()

    
    # -------------------------------------------------
    # STEP 5 - FILTER SUITE ELIGIBILITY
    # -------------------------------------------------

     
    if not dog["suite_allowed"]:

        # Remove every suite
        eligible_rooms = eligible_rooms[
            eligible_rooms["room_type"] != "Suite"
        ].copy()

    

    # -------------------------------------------------
    # STEP 6 - FILTER FLOOR ELIGIBILITY
    # -------------------------------------------------

    if not dog["floor_allowed"]:

        # Remove every floor
        eligible_rooms = eligible_rooms[
            eligible_rooms["room_type"] != "Floor"
        ].copy()

   

    
    # -------------------------------------------------
    # STEP 7 - FILTER ROOMS BY PLAY GROUP
    # -------------------------------------------------

    if dog["play_group"] == "Small":

        # Small-group dogs cannot use the large floor
        eligible_rooms = eligible_rooms[
            ~(
                (eligible_rooms["room_type"] == "Floor")
                &
                (eligible_rooms["size_group"] == "Large")
            )
        ].copy()

        # Small-group dogs may only use Petite Suites
        petite_suite_numbers = [
            "1",
            "2",
            "3",
            "4",
            "6",
            "7",
            "8",
            "9",
            "10"
        ]

        eligible_rooms = eligible_rooms[
            ~(
                (eligible_rooms["room_type"] == "Suite")
                &
                (
                    ~eligible_rooms["room_number"].isin(
                        petite_suite_numbers
                    )
                )
            )
        ].copy()

    elif dog["play_group"] == "Big":

        # Big-group dogs cannot use Petite Suites
        eligible_rooms = eligible_rooms[
            ~(
                (eligible_rooms["room_type"] == "Suite")
                &
                (eligible_rooms["size_group"] == "Petite")
            )
        ].copy()

    elif dog["play_group"] == "Separate":

        # Separate dogs currently keep all eligible room types
        pass 

    # -------------------------------------------------
    # STEP 8 - APPLY FENCE-FIGHTER PRIORITY
    # -------------------------------------------------

    eligible_rooms["special_priority"] = 0

    if dog["fence_fighter"] == 1:

        # Preferred fence-fighter kennels
        eligible_rooms.loc[
            (
                (eligible_rooms["room_type"] == "Kennel")
                &
                (eligible_rooms["room_number"].isin(
                    ["54", "55", "57"]
                ))
            ),
            "special_priority"
        ] = 2

        # Best fence-fighter kennels
        eligible_rooms.loc[
            (
                (eligible_rooms["room_type"] == "Kennel")
                &
                (eligible_rooms["room_number"].isin(
                    ["56", "58"]
                ))
            ),
            "special_priority"
        ] = 1

    # -------------------------------------------------
    # STEP 9A - PROCESS SIBLING GROUP
    # -------------------------------------------------

    sibling_rules = None
    sibling_dogs = pd.DataFrame()

    if pd.notna(dog["sibling_group_id"]):

        sibling_rules = sibling_group_df[
            sibling_group_df["sibling_group_id"]
            ==
            dog["sibling_group_id"]
        ]

        sibling_dogs = daycare[
            daycare["sibling_group_id"]
            ==
            dog["sibling_group_id"]
        ]

    # -------------------------------------------------
    # STEP 9A - PROCESS SIBLING GROUP
    # -------------------------------------------------

    sibling_rules = None
    sibling_dogs = pd.DataFrame()

    if pd.notna(dog["sibling_group_id"]):

        sibling_rules = sibling_group_df[
            sibling_group_df["sibling_group_id"]
            ==
            dog["sibling_group_id"]
        ]

        sibling_dogs = daycare[
            (
                daycare["sibling_group_id"]
                ==
                dog["sibling_group_id"]
            )
            &
            (
                daycare["dog_id"]
                !=
                dog["dog_id"]
            )
        ]
    # -------------------------------------------------
    # STEP 9B - PROCESS SIBLING PLACEMENT RULES
    # -------------------------------------------------

    sibling_placement = "No sibling group"
    shared_room_types = []
    shared_room_priorities = {}

    if sibling_rules is not None and not sibling_rules.empty:

        sibling_rule = sibling_rules.iloc[0]

        keep_together = bool(
            sibling_rule["keep_together"]
        )

        # ---------------------------------------------
        # DETERMINE TOGETHER OR SEPARATE
        # ---------------------------------------------

        if keep_together:

            sibling_placement = "Keep together"

        else:

            sibling_placement = "Assign separately"

        # ---------------------------------------------
        # DETERMINE ALLOWED SHARED ROOM TYPES
        # ---------------------------------------------

        if sibling_rule["shared_suite_allowed"] == 1:

            shared_room_types.append("Suite")

            shared_room_priorities["Suite"] = int(
                sibling_rule["shared_suite_priority"]
            )

        if sibling_rule["shared_floor_allowed"] == 1:

            shared_room_types.append("Floor")

            shared_room_priorities["Floor"] = int(
                sibling_rule["shared_floor_priority"]
            )

        if sibling_rule["shared_kennel_allowed"] == 1:

            shared_room_types.append("Kennel")

            shared_room_priorities["Kennel"] = int(
                sibling_rule["shared_kennel_priority"]

            )

    eligible_rooms_by_dog[dog["dog_id"]] = eligible_rooms.copy() 



# --------------------------------------------
# STEP 10A - Collect sibling groups that stay together
# --------------------------------------------

together_sibling_groups = sibling_group_df[
sibling_group_df["keep_together"] == True
        ].copy()



# --------------------------------------------
# STEP 10B - Collect present dogs
# in each sibling group
# --------------------------------------------

sibling_dogs_by_group = {}

for sibling_group_id in (
    together_sibling_groups["sibling_group_id"]
):

    group_dogs = daycare[
        daycare["sibling_group_id"]
        == sibling_group_id
    ].copy()

    # A shared placement requires at least two dogs
    if len(group_dogs) >= 2:

        sibling_dogs_by_group[
            sibling_group_id
        ] = group_dogs


# --------------------------------------------
# STEP 10C - Build available shared-room
# candidates using sibling overrides
# --------------------------------------------

shared_eligible_rooms_by_group = {}

for sibling_group_id, group_dogs in (
    sibling_dogs_by_group.items()
):

    shared_rooms = available_rooms[
        available_rooms["status"] == 1
    ].copy()

    shared_eligible_rooms_by_group[
        sibling_group_id
    ] = shared_rooms


# --------------------------------------------
# STEP 10D - Filter shared rooms by allowed
# shared room type
# --------------------------------------------

shared_type_filtered_rooms_by_group = {}

for sibling_group_id, shared_rooms in (
    shared_eligible_rooms_by_group.items()
):

    sibling_rule = together_sibling_groups[
        together_sibling_groups["sibling_group_id"]
        == sibling_group_id
    ].iloc[0]

    allowed_shared_room_types = []

    if sibling_rule["shared_suite_allowed"] == 1:
        allowed_shared_room_types.append("Suite")

    if sibling_rule["shared_floor_allowed"] == 1:
        allowed_shared_room_types.append("Floor")

    if sibling_rule["shared_kennel_allowed"] == 1:
        allowed_shared_room_types.append("Kennel")

    filtered_shared_rooms = shared_rooms[
        shared_rooms["shared_room_type"].isin(
            allowed_shared_room_types
        )
    ].copy()

    shared_type_filtered_rooms_by_group[
        sibling_group_id
    ] = filtered_shared_rooms


# --------------------------------------------
# STEP 10E - Filter rooms by sibling capacity
# --------------------------------------------

# --------------------------------------------
# STEP 10E - Filter rooms by allowed
# sibling capacity
# --------------------------------------------

capacity_filtered_rooms_by_group = {}

sibling_size_score = {
    "Small": 1,
    "Medium": 2,
    "Big": 3
}

for sibling_group_id, rooms in (
    shared_type_filtered_rooms_by_group.items()
):

    group_dogs = sibling_dogs_by_group[
        sibling_group_id
    ]

    sibling_sizes = (
        group_dogs["size_class"]
        .astype(str)
        .str.strip()
        .tolist()
    )

    total_size_score = sum(
        sibling_size_score.get(size, 3)
        for size in sibling_sizes
    )

    # Three or more siblings require the largest rooms
    if len(sibling_sizes) >= 3:

        allowed_capacities = [
            "Large"
        ]

    # Small + Small = 2
    elif total_size_score == 2:

        allowed_capacities = [
            "Small",
            "Medium"
        ]

    # Small + Medium = 3
    # Medium + Medium = 4
    # Small + Big = 4
    elif total_size_score in [3, 4]:

        allowed_capacities = [
            "Medium",
            "Medium/Large",
            "Large"
        ]

    # Medium + Big = 5. Two-dog pairs of this size may use the
    # Medium sibling kennels (including 52 and 53).
    elif total_size_score == 5:

        allowed_capacities = [
            "Medium",
            "Medium/Large",
            "Large"
        ]

    # Big + Big = 6
    else:

        allowed_capacities = [
            "Medium/Large",
            "Large"
        ]

    filtered_rooms = rooms[
        rooms["sibling_capacity"].isin(
            allowed_capacities
        )
    ].copy()

    capacity_filtered_rooms_by_group[
        sibling_group_id
    ] = filtered_rooms

   

# --------------------------------------------
# STEP 10F - Select the best shared room
# without double-booking
# --------------------------------------------

selected_sibling_rooms = {}

reserved_sibling_room_ids = set()

capacity_rank = {
    "Small": 1,
    "Medium": 2,
    "Medium/Large": 2,
    "Large": 3
}

for sibling_group_id, rooms in (
    capacity_filtered_rooms_by_group.items()
):

    # Remove rooms already selected by another sibling group
    available_candidate_rooms = rooms[
        ~rooms["room_id"].isin(
            reserved_sibling_room_ids
        )
    ].copy()

    if available_candidate_rooms.empty:
        selected_sibling_rooms[
            sibling_group_id
        ] = None
        continue

    ranked_rooms = available_candidate_rooms.copy()

    # Smaller valid sibling capacity is preferred
    ranked_rooms["capacity_rank"] = (
        ranked_rooms["sibling_capacity"]
        .map(capacity_rank)
        .fillna(999)
    )

    # Lower sibling priority is better
    ranked_rooms["effective_siblings_priority"] = (
        pd.to_numeric(
            ranked_rooms["siblings_priority"],
            errors="coerce"
        )
        .replace(0, 999)
        .fillna(999)
    )

    # Lower general room priority is better
    ranked_rooms["effective_room_priority"] = (
        pd.to_numeric(
            ranked_rooms["priority"],
            errors="coerce"
        )
        .replace(0, 999)
        .fillna(999)
    )

    # Rank sibling preference first,
    # then use the smallest valid room capacity
    ranked_rooms = (
        ranked_rooms
        .sort_values(
            by=[
                "effective_siblings_priority",
                "capacity_rank",
                "effective_room_priority",
                "room_id"
            ]
        )
        .reset_index(drop=True)
    )

    selected_room = ranked_rooms.iloc[0].copy()

    selected_sibling_rooms[
        sibling_group_id
    ] = selected_room

    reserved_sibling_room_ids.add(
        selected_room["room_id"]
    )



# --------------------------------------------
# STEP 10G - Record sibling assignments
# --------------------------------------------

dog_assignments = {}

for sibling_group_id, selected_room in (
    selected_sibling_rooms.items()
):

    if selected_room is None:
        continue

    group_dogs = sibling_dogs_by_group[
        sibling_group_id
    ]

    for _, sibling_dog in group_dogs.iterrows():

        dog_id = sibling_dog["dog_id"]

        dog_assignments[dog_id] = {
    "dog_name": sibling_dog["dog_name"],
    "room_id": selected_room["room_id"],
    "room_number": selected_room["room_number"],
    "room_type": selected_room["room_type"],
    "assignment_type": "Sibling"
}



remaining_daycare = daycare[
    ~daycare["dog_id"].isin(
        dog_assignments.keys()
    )
].copy()

# --------------------------------------------
# STEP 11A - Remove sibling rooms from the
# remaining dogs' eligible rooms
# --------------------------------------------

remaining_eligible_rooms_by_dog = {}

for _, dog in remaining_daycare.iterrows():

    dog_id = dog["dog_id"]

    # Start with this dog's original eligible rooms
    dog_rooms = eligible_rooms_by_dog[
        dog_id
    ].copy()

    # Remove rooms already assigned to siblings
    dog_rooms = dog_rooms[
        ~dog_rooms["room_id"].isin(
            reserved_sibling_room_ids
        )
    ].copy()

    # Save the updated eligible rooms
    remaining_eligible_rooms_by_dog[
        dog_id
    ] = dog_rooms



# --------------------------------------------
# STEP 11B - Analyze remaining dog demand
# --------------------------------------------

remaining_dog_demand = []

for _, dog in remaining_daycare.iterrows():

    dog_id = dog["dog_id"]

    eligible_rooms = (
        remaining_eligible_rooms_by_dog[
            dog_id
        ]
    )

    remaining_dog_demand.append(
        {
            "dog_id": dog_id,
            "dog_name": dog["dog_name"],
            "fence_jumpers": dog["fence_jumpers"],
            "eligible_room_count": len(
                eligible_rooms
            ),
            "eligible_room_types": eligible_rooms[
                "room_type"
            ].nunique()
        }
    )

remaining_dog_demand_df = pd.DataFrame(
    remaining_dog_demand,
    columns=[
        "dog_id",
        "dog_name",
        "fence_jumpers",
        "eligible_room_count",
        "eligible_room_types"
    ]
)

if not remaining_dog_demand_df.empty:

    remaining_dog_demand_df = (
        remaining_dog_demand_df
        .sort_values(
            by=[
                "fence_jumpers",
                "eligible_room_count",
                "eligible_room_types"
            ],
            ascending=[
                False,
                True,
                True
            ]
        )
        .reset_index(drop=True)
    )


# --------------------------------------------
# STEP 12A - Remove already reserved rooms
# --------------------------------------------

reserved_room_ids = {
    assignment["room_id"]
    for assignment in dog_assignments.values()
    if assignment.get("room_id") is not None
}

available_rooms_by_remaining_dog = {}

for _, dog in remaining_dog_demand_df.iterrows():

    dog_id = dog["dog_id"]

    dog_eligible_rooms = eligible_rooms_by_dog.get(
        dog_id,
        pd.DataFrame()
    ).copy()

    if dog_eligible_rooms.empty:
        available_rooms_by_remaining_dog[dog_id] = dog_eligible_rooms
        continue

    dog_available_rooms = dog_eligible_rooms[
        ~dog_eligible_rooms["room_id"].isin(
            reserved_room_ids
        )
    ].copy()

    available_rooms_by_remaining_dog[dog_id] = (
        dog_available_rooms
    )


# --------------------------------------------
# STEP 12B - Rank available rooms for each dog
# --------------------------------------------

ranked_rooms_by_dog = {}

priority_column_by_room_type = {
    "Crate": "crate_priority",
    "Kennel": "kennel_priority",
    "Suite": "suite_priority",
    "Floor": "floor_priority"
}

# Count remaining fence fighters
remaining_fence_fighter_count = (
    remaining_dog_demand_df["dog_id"]
    .isin(
        daycare.loc[
            daycare["fence_fighter"] == 1,
            "dog_id"
        ]
    )
    .sum()
)

for _, demand_row in remaining_dog_demand_df.iterrows():

    dog_id = demand_row["dog_id"]

    # Get the dog's full record
    dog = daycare.loc[
        daycare["dog_id"] == dog_id
    ].iloc[0]

    # Get this dog's available rooms
    dog_rooms = available_rooms_by_remaining_dog[
        dog_id
    ].copy()

    if dog_rooms.empty:
        ranked_rooms_by_dog[dog_id] = dog_rooms
        continue

    # Add the dog's preference for each room type
    dog_rooms["dog_room_type_priority"] = (
        dog_rooms["room_type"]
        .map(priority_column_by_room_type)
        .apply(lambda column: dog[column])
    )

    # Default: all rooms have the same fence-fighter ranking
    dog_rooms["fence_fighter_room_priority"] = 10

    if bool(dog["fence_fighter"]):

        # One fence fighter prefers Kennel 57
        if remaining_fence_fighter_count == 1:
            preferred_fence_fighter_kennels = {
                "57": 0
            }

        # Two or more fence fighters prefer 56 and 58
        else:
            preferred_fence_fighter_kennels = {
                "56": 0,
                "58": 1
            }

        kennel_numbers = (
            dog_rooms["room_number"]
            .astype(str)
            .str.strip()
        )

        for kennel_number, rank in (
            preferred_fence_fighter_kennels.items()
        ):

            dog_rooms.loc[
                (
                    dog_rooms["room_type"] == "Kennel"
                )
                & (
                    kennel_numbers == kennel_number
                ),
                "fence_fighter_room_priority"
            ] = rank

    # Rank rooms
    dog_rooms = (
        dog_rooms
        .sort_values(
            by=[
                "dog_room_type_priority",
                "fence_fighter_room_priority",
                "priority",
                "room_id"
            ]
        )
        .reset_index(drop=True)
    )

    ranked_rooms_by_dog[dog_id] = dog_rooms



# --------------------------------------------
# HELPER - Find adjacent kennels
# --------------------------------------------

kennel_sections = [
    [42, 43, 44, 45, 46],
    [47, 48, 49, 50, 51, 52, 53],
    [54, 55, 56, 57, 58],
    [59, 60]
]


def get_adjacent_kennels(room_number):

    room_number = int(room_number)

    for section in kennel_sections:

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


# --------------------------------------------
# STEP 12C - Assign remaining daycare dogs
# --------------------------------------------

unassigned_dogs = []

fence_fighter_blocked_room_ids = set()

# Rooms occupied by boarding dogs
boarding_room_ids = set(
    dogs_df.loc[
        dogs_df["boarding_status"] == 1,
        "assigned_room_id"
    ]
    .dropna()
    .astype(int)
    .tolist()
)

# Make boarding rooms unavailable during daycare assignment
reserved_room_ids.update(
    boarding_room_ids
)

for _, demand_row in remaining_dog_demand_df.iterrows():

    dog_id = demand_row["dog_id"]
    dog_name = demand_row["dog_name"]

    dog = daycare.loc[
        daycare["dog_id"] == dog_id
    ].iloc[0]

    ranked_rooms = ranked_rooms_by_dog.get(
        dog_id,
        pd.DataFrame()
    ).copy()

    # Remove rooms already assigned or blocked
    if not ranked_rooms.empty:

        ranked_rooms = ranked_rooms[
            ~ranked_rooms["room_id"].isin(
                reserved_room_ids
                | fence_fighter_blocked_room_ids
            )
        ].copy()

    # Fence fighters cannot be placed beside
    # an occupied kennel
    if (
        bool(dog["fence_fighter"])
        and not ranked_rooms.empty
    ):

        occupied_kennel_numbers = set(
            rooms_df.loc[
                (
                    rooms_df["room_id"].isin(
                        reserved_room_ids
                    )
                )
                &
                (
                    rooms_df["room_type"] == "Kennel"
                ),
                "room_number"
            ]
            .astype(str)
            .str.strip()
            .tolist()
        )

        def fence_fighter_kennel_is_safe(room):

            # Non-kennel rooms are unaffected
            if room["room_type"] != "Kennel":
                return True

            adjacent_kennel_numbers = (
                get_adjacent_kennels(
                    room["room_number"]
                )
            )

            return not any(
                str(kennel_number)
                in occupied_kennel_numbers
                for kennel_number
                in adjacent_kennel_numbers
            )

        ranked_rooms = ranked_rooms[
            ranked_rooms.apply(
                fence_fighter_kennel_is_safe,
                axis=1
            )
        ].copy()

    # No legal room remains
    if ranked_rooms.empty:

        unassigned_dogs.append(
            {
                "dog_id": dog_id,
                "dog_name": dog_name,
                "reason": "No available eligible room"
            }
        )

        continue

    # Select the best remaining room
    selected_room = ranked_rooms.iloc[0]

    room_id = selected_room["room_id"]
    room_number = selected_room["room_number"]
    room_type = selected_room["room_type"]

    # Save the assignment
    dog_assignments[dog_id] = {
        "dog_name": dog_name,
        "room_id": room_id,
        "room_number": room_number,
        "room_type": room_type,
        "assignment_type": "Individual"
    }

    # Reserve the selected room
    reserved_room_ids.add(room_id)

    # Block neighboring kennels after assigning
    # a fence fighter to a kennel
    if (
        bool(dog["fence_fighter"])
        and room_type == "Kennel"
    ):

        adjacent_kennel_numbers = (
            get_adjacent_kennels(
                room_number
            )
        )

        adjacent_room_ids = rooms_df.loc[
            (
                rooms_df["room_type"] == "Kennel"
            )
            &
            (
                rooms_df["room_number"]
                .astype(str)
                .str.strip()
                .isin(
                    [
                        str(number)
                        for number
                        in adjacent_kennel_numbers
                    ]
                )
            ),
            "room_id"
        ].tolist()

        fence_fighter_blocked_room_ids.update(
            adjacent_room_ids
        )


# --------------------------------------------
# STEP 13A - Build final assignment DataFrame
# --------------------------------------------

final_assignments = []

for dog_id, assignment in dog_assignments.items():

    final_assignments.append({
        "dog_id": dog_id,
        "dog_name": assignment["dog_name"],
        "room_id": assignment["room_id"],
        "room_number": assignment["room_number"],
        "room_type": assignment["room_type"],
        "assignment_type": assignment["assignment_type"]
    })

final_assignments_df = pd.DataFrame(
    final_assignments
)



# --------------------------------------------
# STEP 13B - Display final assignments
# BOARDING DOGS REPORT
# --------------------------------------------


report_date = dogs_df["attendance_date"].iloc[0]

print("=" * 60)
print("DOG DAYCARE AUTOMATION REPORT")
print("=" * 60)
print(f"Date: {report_date}")


boarding_report_df = (
    dogs_df[
        dogs_df["boarding_status"] == 1
    ]
    .merge(
        rooms_df[
            [
                "room_id",
                "room_number",
                "room_name"
            ]
        ],
        left_on="assigned_room_id",
        right_on="room_id",
        how="left"
    )
    .sort_values(
        by=[
            "room_id",
            "dog_name"
        ]
    )
    [
        [
            "dog_name",
            "room_number",
            "room_name",
            "play_group"
        ]
    ]
    .reset_index(drop=True)
)


print("\n" + "=" * 60)
print("BOARDING DOGS")
print("=" * 60)

if boarding_report_df.empty:

    print("No boarding dogs.")

else:

    print(
        boarding_report_df.to_string(
            index=False
        )
    )

if dogs_df.empty:

    print("No attendance records found for today.")
    raise SystemExit

report_date = dogs_df["attendance_date"].iloc[0]

print("=" * 60)
print("DOG DAYCARE AUTOMATION REPORT")
print("=" * 60)
print(f"Date: {report_date}")


# -----------------------------------------------------
# BUILD FINAL DAYCARE REPORT
# -----------------------------------------------------


final_daycare_report_records = []

for dog_id, assignment in dog_assignments.items():

    dog_record = dogs_df.loc[
        dogs_df["dog_id"] == dog_id
    ].iloc[0]

    room_record = rooms_df.loc[
        rooms_df["room_id"] == assignment["room_id"]
    ].iloc[0]

    final_daycare_report_records.append(
        {
            "dog_name": dog_record["dog_name"],
            "play_group": dog_record["play_group"],
            "room_name": room_record["room_name"],
            "room_number": room_record["room_number"],
            "room_type": room_record["room_type"]
        }
    )

final_daycare_report_df = pd.DataFrame(
    final_daycare_report_records
)


# -----------------------------------------------------
# DAYCARE BIG PLAY GROUP
# -----------------------------------------------------

daycare_big_report_df = (
    final_daycare_report_df[
        final_daycare_report_df["play_group"] == "Big"
    ]
    [
        [
            "dog_name",
            "room_name",
            "room_number",
            "room_type"
        ]
    ]
    .sort_values(
        by="dog_name",
        key=lambda column: column.str.lower()
    )
    .reset_index(drop=True)
)


print("\n" + "=" * 60)
print("DAYCARE BIG PLAY GROUP")
print("=" * 60)

if daycare_big_report_df.empty:

    print("No dogs in the Big play group.")

else:

    print(
        daycare_big_report_df.to_string(
            index=False
        )
    )


# -----------------------------------------------------
# DAYCARE PETITE PLAY GROUP
# -----------------------------------------------------

daycare_petite_report_df = (
    final_daycare_report_df[
        final_daycare_report_df["play_group"] == "Small"
    ]
    [
        [
            "dog_name",
            "room_name",
            "room_number",
            "room_type"
        ]
    ]
    .sort_values(
        by="dog_name",
        key=lambda column: column.str.lower()
    )
    .reset_index(drop=True)
)


print("\n" + "=" * 60)
print("DAYCARE PETITE PLAY GROUP")
print("=" * 60)

if daycare_petite_report_df.empty:

    print("No dogs in the Petite play group.")

else:

    print(
        daycare_petite_report_df.to_string(
            index=False
        )
    )


# =====================================================
# BUILD FINAL REMAINING ROOMS
# =====================================================

# Boarding rooms currently occupied
boarding_room_ids = set(
    dogs_df.loc[
        dogs_df["boarding_status"] == 1,
        "assigned_room_id"
    ]
    .dropna()
    .astype(int)
    .tolist()
)

# Daycare rooms assigned by the algorithm
daycare_room_ids = {
    int(assignment["room_id"])
    for assignment in dog_assignments.values()
    if assignment.get("room_id") is not None
}

# Rooms blocked beside fence fighters
blocked_kennel_ids = {
    int(room_id)
    for room_id in fence_fighter_blocked_room_ids
}

# Every room unavailable after today's assignments
used_or_blocked_room_ids = (
    boarding_room_ids
    | daycare_room_ids
    | blocked_kennel_ids
)

# Keep only rooms whose database status is available
available_status_values = {
    "available",
    "open",
    "active",
    "yes",
    "true",
    "1"
}

active_room_mask = (
    rooms_df["status"]
    .astype(str)
    .str.strip()
    .str.lower()
    .isin(available_status_values)
)

# Final open rooms after boarding and daycare assignments
remaining_rooms_df = rooms_df.loc[
    active_room_mask
    & ~rooms_df["room_id"].isin(
        used_or_blocked_room_ids
    )
].copy()

remaining_rooms_df = (
    remaining_rooms_df
    .sort_values(
        by=[
            "room_type",
            "size_group",
            "priority",
            "room_id"
        ],
        na_position="last"
    )
    .reset_index(drop=True)
)


# =====================================================
# BIG GROUP REMAINING SPACE REPORT
# =====================================================

big_remaining_rooms_df = remaining_rooms_df.copy()

# Clean values for reliable filtering
big_remaining_rooms_df["room_type_clean"] = (
    big_remaining_rooms_df["room_type"]
    .astype(str)
    .str.strip()
    .str.upper()
)

big_remaining_rooms_df["size_group_clean"] = (
    big_remaining_rooms_df["size_group"]
    .astype(str)
    .str.strip()
    .str.upper()
)

big_remaining_rooms_df["room_number_clean"] = (
    big_remaining_rooms_df["room_number"]
    .astype(str)
    .str.strip()
    .str.upper()
)

big_remaining_rooms_df["room_number_numeric"] = pd.to_numeric(
    big_remaining_rooms_df["room_number"],
    errors="coerce"
)


# -----------------------------------------------------
# BIG GROUP CRATE AVAILABILITY
# -----------------------------------------------------

medium_crates_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("CRATE")
        &
        big_remaining_rooms_df["size_group_clean"].eq("M")
    ).sum()
)

large_crates_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("CRATE")
        &
        big_remaining_rooms_df["size_group_clean"].eq("L")
    ).sum()
)

xl_crates_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("CRATE")
        &
        big_remaining_rooms_df["size_group_clean"].eq("XL")
    ).sum()
)

xxl_crates_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("CRATE")
        &
        big_remaining_rooms_df["size_group_clean"].eq("XXL")
    ).sum()
)


# -----------------------------------------------------
# BIG GROUP ROOM AVAILABILITY
# -----------------------------------------------------

small_floor_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("FLOOR")
        &
        big_remaining_rooms_df["room_number_clean"].eq("SMFL")
    ).sum()
)

suites_11_25_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("SUITE")
        &
        big_remaining_rooms_df["room_number_numeric"].between(
            11,
            25
        )
    ).sum()
)

kennels_42_53_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("KENNEL")
        &
        big_remaining_rooms_df["room_number_numeric"].between(
            42,
            53
        )
    ).sum()
)

crate_room_kennels_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("KENNEL")
        &
        big_remaining_rooms_df["room_number_numeric"].isin(
            [59, 60]
        )
    ).sum()
)

front_kennels_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("KENNEL")
        &
        big_remaining_rooms_df["room_number_numeric"].between(
            54,
            58
        )
    ).sum()
)

backhall_suites_available = int(
    (
        big_remaining_rooms_df["room_type_clean"].eq("SUITE")
        &
        big_remaining_rooms_df["room_number_numeric"].isin(
            [27, 28, 29]
        )
    ).sum()
)


# -----------------------------------------------------
# DISPLAY BIG GROUP AVAILABILITY
# -----------------------------------------------------

print("\n" + "=" * 60)
print("BIG GROUP REMAINING SPACE")
print("=" * 60)

print("\nCRATE AVAILABILITY")
print("-" * 30)

print(f"M Crates:                 {medium_crates_available}")
print(f"L Crates:                 {large_crates_available}")
print(f"XL Crates:                {xl_crates_available}")
print(f"XXL Crates:               {xxl_crates_available}")

print("\nAVAILABLE ROOMS")
print("-" * 30)

print(f"Small Floor (SMFL):       {small_floor_available}")
print(f"Suites (11-25):           {suites_11_25_available}")
print(f"Kennels (42-53):          {kennels_42_53_available}")
print(f"Crate Room Kennels:       {crate_room_kennels_available}")
print(f"Front Kennels (54-58):    {front_kennels_available}")
print(f"Backhall Suites (27-29):  {backhall_suites_available}")


# -----------------------------------------------------
# BUILD LIST OF ALL AVAILABLE BIG-GROUP ROOMS
# -----------------------------------------------------

big_group_room_mask = (
    (
        big_remaining_rooms_df["room_type_clean"].eq("CRATE")
        &
        big_remaining_rooms_df["size_group_clean"].isin(
            ["M", "L", "XL", "XXL"]
        )
    )
    |
    (
        big_remaining_rooms_df["room_type_clean"].eq("FLOOR")
        &
        big_remaining_rooms_df["room_number_clean"].eq("SMFL")
    )
    |
    (
        big_remaining_rooms_df["room_type_clean"].eq("SUITE")
        &
        (
            big_remaining_rooms_df["room_number_numeric"]
            .between(11, 25)
            |
            big_remaining_rooms_df["room_number_numeric"]
            .isin([27, 28, 29])
        )
    )
    |
    (
        big_remaining_rooms_df["room_type_clean"].eq("KENNEL")
        &
        big_remaining_rooms_df["room_number_numeric"]
        .between(42, 60)
    )
)

available_big_group_rooms_df = (
    big_remaining_rooms_df[
        big_group_room_mask
    ][
        [
            "room_number",
            "room_name",
            "room_type",
            "size_group"
        ]
    ]
    .sort_values(
        by=[
            "room_type",
            "size_group",
            "room_number"
        ]
    )
    .reset_index(drop=True)
)


# -----------------------------------------------------
# DISPLAY ALL AVAILABLE BIG-GROUP ROOMS
# -----------------------------------------------------

print("\nALL AVAILABLE BIG-GROUP ROOMS")
print("-" * 60)

if available_big_group_rooms_df.empty:

    print("No Big Group rooms are available.")

else:

    print(
        available_big_group_rooms_df.to_string(
            index=False
        )
    )

# =====================================================
# UNASSIGNED DOGS
# =====================================================

print("\n" + "=" * 60)
print("UNASSIGNED DOGS")
print("=" * 60)

if not unassigned_dogs:

    print("None")

else:

    unassigned_dogs_df = (
        pd.DataFrame(unassigned_dogs)
        .merge(
            dogs_df[
                [
                    "dog_id",
                    "play_group"
                ]
            ],
            on="dog_id",
            how="left"
        )
        [
            [
                "dog_name",
                "play_group",
                "reason"
            ]
        ]
        .sort_values(
            by="dog_name",
            key=lambda column: column.str.lower()
        )
        .reset_index(drop=True)
    )

    print(
        unassigned_dogs_df.to_string(
            index=False
        )
    )

# =====================================================
# TODAY'S ATTENDANCE TOTALS
# =====================================================

big_group_count = len(
    dogs_df[
        dogs_df["play_group"] == "Big"
    ]
)

petite_group_count = len(
    dogs_df[
        dogs_df["play_group"] == "Small"
    ]
)

boarding_count = len(
    dogs_df[
        dogs_df["boarding_status"] == 1
    ]
)

daycare_count = len(
    dogs_df[
        dogs_df["boarding_status"] == 0
    ]
)

total_dogs = len(dogs_df)

print("\n============================================================")
print("TODAY'S ATTENDANCE TOTALS")
print("============================================================")

print(f"Total Dogs Today:      {total_dogs}")
print(f"Boarding Dogs:         {boarding_count}")
print(f"Daycare Dogs:          {daycare_count}")
print(f"Big Play Group:        {big_group_count}")
print(f"Petite Play Group:     {petite_group_count}")

big_remaining_rooms_df = remaining_rooms_df.copy()
