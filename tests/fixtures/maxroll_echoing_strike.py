"""Maxroll Echoing Strike MF build reference loadout.

This fixture represents the standard endgame gear set from Maxroll's guide.
Used as ground truth for formula calibration (Layer 2 validation).

Source: https://maxroll.gg/d2/guides/echoing-strike-warlock-guide
"""

MAXROLL_STANDARD_GEAR = {
    "weapon": {
        "name": "Arioc's Needle",
        "stats": {"all_skills": 4, "fcr": 50, "damage_max": 180, "ed": 200, "ias": 30},
    },
    "shield": {
        "name": "Spirit Monarch",
        "stats": {"all_skills": 2, "fcr": 35, "vitality": 22, "mana": 112, "fhr": 55},
    },
    "helmet": {
        "name": "Harlequin Crest",
        "stats": {"all_skills": 2, "life": 98, "mana": 98, "dr": 10, "mf": 50},
    },
    "body": {
        "name": "Enigma",
        "stats": {"all_skills": 2, "strength": 45, "frw": 45, "mf": 1, "life": 100},
    },
    "gloves": {
        "name": "Trang-Oul's Claws",
        "stats": {"fcr": 20, "resist_cold": 30},
    },
    "belt": {
        "name": "Arachnid Mesh",
        "stats": {"all_skills": 1, "fcr": 20, "mana": 5},
    },
    "boots": {
        "name": "Sandstorm Trek",
        "stats": {
            "strength": 15,
            "vitality": 15,
            "fhr": 20,
            "frw": 20,
            "resist_poison": 50,
        },
    },
    "amulet": {
        "name": "Mara's Kaleidoscope",
        "stats": {"all_skills": 2, "resist_all": 25},
    },
    "ring1": {
        "name": "Stone of Jordan",
        "stats": {"all_skills": 1, "mana": 250},
    },
    "ring2": {
        "name": "Bul-Kathos' Wedding Band",
        "stats": {"all_skills": 1, "life": 50, "ll": 3},
    },
}

# Expected aggregate stats (approximate — for validation within 5% tolerance)
EXPECTED_AGGREGATE = {
    "all_skills": 15,
    "fcr": 125,
    "mf": 51,
    "life": 248,  # 98 (Shako) + 100 (Enigma) + 50 (BK) = 248
    "mana": 465,
    "fhr": 75,
    "dr": 10,
}
