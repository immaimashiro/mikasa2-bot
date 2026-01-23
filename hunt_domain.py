# hunt_domain.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta

import hunt_services as hs
from services import now_fr, now_iso, normalize_code, display_name

# Avatars direction (tags + urls = tu mettras tes liens d’images)
DIRECTION_AVATARS = [
    {"tag": "MAI",   "label": "Mai",   "url": "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Mai.png"},   # <- mets tes URLs
    {"tag": "ROXY",  "label": "Roxy",  "url": "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Roxy.png"},
    {"tag": "LYA",   "label": "Lya",   "url": "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Lya.png"},
    {"tag": "ZACKO", "label": "Zacko", "url": "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Zacko.png"},
    {"tag": "DRACO", "label": "Draco", "url": "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Draco.png"},
]

def direction_by_tag(tag: str) -> Optional[Dict[str, Any]]:
    t = (tag or "").strip().upper()
    for a in DIRECTION_AVATARS:
        if a["tag"] == t:
            return a
    return None

# ----------------------------
# PLAYERS
# ----------------------------
def get_player_row(sheets, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = sheets.get_all_records(hs.T_PLAYERS)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def ensure_player(
    sheets,
    *,
    discord_id: int,
    vip_code: str,
    pseudo: str,
    is_employee: bool
) -> Tuple[int, Dict[str, Any]]:
    row_i, row = get_player_row(sheets, discord_id)
    if row_i and row:
        # refresh champs “vivants”
        sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "vip_code", normalize_code(vip_code))
        sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "pseudo", display_name(pseudo))
        sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "is_employee", "1" if is_employee else "0")
        sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "updated_at", now_iso())
        return row_i, row

    sheets.append_by_headers(hs.T_PLAYERS, {
        "discord_id": str(discord_id),
        "vip_code": normalize_code(vip_code),
        "pseudo": display_name(pseudo),
        "is_employee": "1" if is_employee else "0",
        "avatar_tag": "",
        "avatar_url": "",
        "ally_tag": "",
        "ally_url": "",
        "level": 1,
        "xp": 0,
        "xp_total": 0,
        "stats_hp": 100,
        "stats_atk": 10,
        "stats_def": 8,
        "stats_luck": 5,
        "hunt_dollars": 0,
        "inventory_json": "",
        "jail_until": "",
        "last_daily_date": "",
        "weekly_week_key": "",
        "weekly_wins": 0,
        "total_runs": 0,
        "total_deaths": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    row_i2, row2 = get_player_row(sheets, discord_id)
    if not row_i2 or not row2:
        raise RuntimeError("Impossible de créer le player.")
    return row_i2, row2

def set_avatar(sheets, discord_id: int, avatar_tag: str, avatar_url: str):
    row_i, row = get_player_row(sheets, discord_id)
    if not row_i:
        return False, "Player introuvable."
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "avatar_tag", avatar_tag)
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "avatar_url", avatar_url)
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "updated_at", now_iso())
    return True, ""

# ----------------------------
# PRISON
# ----------------------------
def jail_until_dt(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # stored as ISO UTC
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None

def is_in_jail(player: Dict[str, Any]) -> Tuple[bool, Optional[datetime]]:
    dt = jail_until_dt(str(player.get("jail_until", "")).strip())
    if not dt:
        return False, None
    return (datetime.now(tz=dt.tzinfo) < dt), dt

def apply_jail(sheets, row_i: int, hours: int):
    hours = max(1, min(12, int(hours)))
    until = datetime.now(tz=timedelta(0)) + timedelta(hours=hours)  # UTC-ish
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "jail_until", until.isoformat(timespec="seconds"))

# ----------------------------
# DAILY
# ----------------------------
def daily_exists(sheets, discord_id: int, date_key: str) -> bool:
    rows = sheets.get_all_records(hs.T_DAILY)
    for r in rows:
        if str(r.get("discord_id", "")).strip() == str(discord_id) and str(r.get("date_key", "")).strip() == date_key:
            return True
    return False

def append_daily(
    sheets,
    *,
    date_key: str,
    discord_id: int,
    vip_code: str,
    result: str,
    story: str,
    rolls: str,
    rewards_json: str,
    money_delta: int,
    xp_delta: int,
    jail_delta_hours: int
):
    sheets.append_by_headers(hs.T_DAILY, {
        "date_key": date_key,
        "discord_id": str(discord_id),
        "vip_code": normalize_code(vip_code),
        "result": result,
        "story": story,
        "rolls": rolls,
        "rewards_json": rewards_json,
        "money_delta": int(money_delta),
        "xp_delta": int(xp_delta),
        "jail_delta_hours": int(jail_delta_hours),
        "created_at": now_iso(),
    })


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
