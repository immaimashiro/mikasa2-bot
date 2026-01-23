import random

LOOT_TABLE = {
    "NORMAL": [
        {"item_id": "BANDAGE",        "qty_min": 1, "qty_max": 3, "weight": 45, "rarity": "COMMON"},
        {"item_id": "KIT_DE_SOIN",    "qty_min": 1, "qty_max": 1, "weight": 18, "rarity": "UNCOMMON"},
        {"item_id": "COUTEAU",        "qty_min": 1, "qty_max": 1, "weight": 14, "rarity": "UNCOMMON"},
        {"item_id": "BATTE",          "qty_min": 1, "qty_max": 1, "weight": 10, "rarity": "RARE"},
        {"item_id": "PISTOLET",       "qty_min": 1, "qty_max": 1, "weight": 7,  "rarity": "RARE"},
        {"item_id": "SMG",            "qty_min": 1, "qty_max": 1, "weight": 3,  "rarity": "EPIC"},
        {"item_id": "JAILBREAK_PASS", "qty_min": 1, "qty_max": 1, "weight": 1,  "rarity": "RARE"},       # carte sortie prison (rare)
        {"item_id": "LUCILLE",        "qty_min": 1, "qty_max": 1, "weight": 0.4,"rarity": "LEGENDARY"},  # ultra rare
    ],
    "GOLD": [
        {"item_id": "BANDAGE",        "qty_min": 2, "qty_max": 5, "weight": 35, "rarity": "COMMON"},
        {"item_id": "KIT_DE_SOIN",    "qty_min": 1, "qty_max": 2, "weight": 20, "rarity": "UNCOMMON"},
        {"item_id": "COUTEAU",        "qty_min": 1, "qty_max": 1, "weight": 14, "rarity": "UNCOMMON"},
        {"item_id": "BATTE",          "qty_min": 1, "qty_max": 1, "weight": 12, "rarity": "RARE"},
        {"item_id": "PISTOLET",       "qty_min": 1, "qty_max": 1, "weight": 10, "rarity": "RARE"},
        {"item_id": "SMG",            "qty_min": 1, "qty_max": 1, "weight": 6,  "rarity": "EPIC"},
        {"item_id": "JAILBREAK_PASS", "qty_min": 1, "qty_max": 1, "weight": 3,  "rarity": "RARE"},       # + fréquent
        {"item_id": "LUCILLE",        "qty_min": 1, "qty_max": 1, "weight": 1.2,"rarity": "LEGENDARY"},  # plus accessible mais reste rare
    ],
}


def roll_loot(key_type: str = "NORMAL", *, jailed_bonus: bool = False):
    """
    Retourne (item_id, qty, rarity).
    jailed_bonus: si le joueur est en prison au moment d'ouvrir, on boost un peu JAILBREAK_PASS.
    """
    table = LOOT_TABLE.get(key_type.upper(), LOOT_TABLE["NORMAL"])

    # Copie locale + bonus prison (petit boost)
    entries = []
    for e in table:
        ee = dict(e)
        if jailed_bonus and ee["item_id"] == "JAILBREAK_PASS":
            ee["weight"] = float(ee["weight"]) + 2.0
        entries.append(ee)

    total = sum(float(e["weight"]) for e in entries)
    r = random.random() * total
    acc = 0.0
    pick = entries[-1]
    for e in entries:
        acc += float(e["weight"])
        if r <= acc:
            pick = e
            break

    qty = random.randint(int(pick["qty_min"]), int(pick["qty_max"]))
    return pick["item_id"], qty, pick["rarity"]

