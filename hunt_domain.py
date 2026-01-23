# hunt_domain.py
# -*- coding: utf-8 -*-

from __future__ import annotations
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

ENEMIES = [
    {"id":"COYOTTE", "name":"Coyotte", "hp":10, "atk":3},
    {"id":"RAT_MUTANT", "name":"Rat mutant", "hp":12, "atk":4},
    {"id":"PUMA", "name":"Puma", "hp":14, "atk":5},
    {"id":"VOYOU", "name":"Voyou", "hp":11, "atk":4},
]

SCENES = [
    "Une ruelle de Davis sent la poudre et le ketchup renversé. Mikasa plisse les yeux.",
    "Une porte de service claque à Strawberry. L’air goûte la fuite et les ennuis.",
    "Un néon de Vespucci grésille. Quelque chose bouge derrière les poubelles.",
    "Downtown. Les vitrines reflètent ton visage, et pas que ton visage.",
]

def d20() -> int:
    return random.randint(1, 20)

def new_daily_state(player: dict) -> dict:
    enemy = random.choice(ENEMIES)
    return {
        "scene": random.choice(SCENES),
        "turn": 1,
        "player_hp": int(player.get("stats_hp", 20) or 20),
        "player_hp_max": int(player.get("stats_hp_max", 20) or 20),
        "enemy": {"id": enemy["id"], "name": enemy["name"], "hp": enemy["hp"], "hp_max": enemy["hp"], "atk": enemy["atk"]},
        "log": [],
        "done": False,
        "reward_xp": 0,
        "reward_dollars": 0,
        "died": False,
        "jailed": False,
        "jail_hours": 0,
    }

def apply_attack(state: dict, player: dict) -> dict:
    atk = int(player.get("stats_atk", 3) or 3)
    per = int(player.get("stats_per", 2) or 2)

    roll = d20()
    dmg = max(1, atk + (1 if roll >= 15 else 0) - (0 if roll >= 5 else 1))
    # petit bonus perception: critique “propre”
    if roll == 20:
        dmg += 3

    state["enemy"]["hp"] = max(0, int(state["enemy"]["hp"]) - dmg)
    state["log"].append(f"🗡️ Jet d’attaque: **{roll}** → tu infliges **{dmg}** dégâts.")

    if state["enemy"]["hp"] <= 0:
        state["done"] = True
        # reward: un peu de RNG mais raisonnable
        bonus = d20()
        dollars = 10 + (bonus // 2)
        xp = 3 + (1 if bonus >= 15 else 0)
        state["reward_dollars"] += dollars
        state["reward_xp"] += xp
        state["log"].append(f"🏁 Ennemi vaincu. Butin: **+{dollars} Hunt$**, **+{xp} XP**.")
        return state

    # Ennemi riposte
    return apply_enemy_turn(state, player)

def apply_enemy_turn(state: dict, player: dict) -> dict:
    df = int(player.get("stats_def", 2) or 2)
    roll = d20()
    raw = int(state["enemy"]["atk"]) + (1 if roll >= 16 else 0)
    dmg = max(0, raw - df)

    state["player_hp"] = max(0, int(state["player_hp"]) - dmg)
    state["log"].append(f"🐾 Riposte {state['enemy']['name']}: jet **{roll}** → tu prends **{dmg}** dégâts.")

    if state["player_hp"] <= 0:
        state["done"] = True
        state["died"] = True
        # mort = perte partielle (soft)
        # on fait perdre surtout de l’argent, pas ton “niveau”
        state["reward_dollars"] = max(0, int(state["reward_dollars"]) - 5)
        state["reward_xp"] = max(0, int(state["reward_xp"]) - 1)
        state["log"].append("💀 Tu t’écroules. Mikasa te tire par le col hors du danger… mais ça pique.")
    else:
        state["turn"] += 1

    return state

def apply_steal(state: dict, player: dict) -> dict:
    # voler = gain Hunt$ mais risque prison
    cha = int(player.get("stats_cha", 2) or 2)
    luck = int(player.get("stats_luck", 1) or 1)
    roll = d20()

    if roll + cha + luck >= 18:
        gain = 15 + (roll // 3)
        state["reward_dollars"] += gain
        state["log"].append(f"👜 Vol réussi: jet **{roll}** → **+{gain} Hunt$**. Personne n’a rien vu… presque.")
    else:
        # prison max 12h (tu veux)
        hours = min(12, max(2, 6 + (18 - (roll + cha)) // 2))
        state["done"] = True
        state["jailed"] = True
        state["jail_hours"] = hours
        state["log"].append(f"🚨 Vol raté: jet **{roll}** → menottes. **Prison {hours}h**.")
    return state

def apply_heal(state: dict, player: dict) -> dict:
    # heal simple (sans conso d’items pour l’instant)
    roll = d20()
    heal = 3 + (2 if roll >= 15 else 0)
    state["player_hp"] = min(int(state["player_hp_max"]), int(state["player_hp"]) + heal)
    state["log"].append(f"🩹 Tu te soignes: jet **{roll}** → **+{heal} PV**.")
    # ennemi joue
    return apply_enemy_turn(state, player)
