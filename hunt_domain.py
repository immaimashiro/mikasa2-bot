# hunt_domain.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
from datetime import datetime, timedelta
import random
import json

import hunt_data as hda
import hunt_services as hs
from services import SheetsService, now_fr, now_iso, normalize_code, display_name

# ------------------------------------
# Equip slots (alignés sur hs.equipped_json)
# ------------------------------------
EQUIP_SLOTS = {
    "weapon": "weapon",
    "armor": "armor",
    "stim": "stim",
}

# ==========================================================
# AVATARS (Direction SubUrban)
# (si tu utilises déjà hda.AVATARS, tu peux supprimer ce bloc)
# ==========================================================
DIRECTION_AVATARS: List[Dict[str, str]] = [
    {"tag": "MAI",   "label": "Mai",   "url": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Mai.png"},
    {"tag": "ROXY",  "label": "Roxy",  "url": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Roxy.png"},
    {"tag": "LYA",   "label": "Lya",   "url": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Lya.png"},
    {"tag": "ZACKO", "label": "Zacko", "url": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Zacko.png"},
    {"tag": "DRACO", "label": "Draco", "url": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Draco.png"},
]

def direction_by_tag(tag: str) -> Optional[Dict[str, str]]:
    t = (tag or "").strip().upper()
    for a in DIRECTION_AVATARS:
        if a["tag"] == t:
            return a
    return None

def pick_random_direction(exclude: Optional[List[str]] = None) -> Dict[str, str]:
    ex = set([(x or "").strip().upper() for x in (exclude or []) if (x or "").strip()])
    pool = [a for a in DIRECTION_AVATARS if a["tag"] not in ex] or DIRECTION_AVATARS[:]
    return random.choice(pool)

# ==========================================================
# DÉS
# ==========================================================
def d20() -> int:
    return random.randint(1, 20)

# ==========================================================
# ENNEMIS / SCÈNES (base)
# ==========================================================
ENEMIES = [
    {"id": "COYOTE", "name": "Coyote affamé", "hp": 10, "atk": 3},
    {"id": "RAT_MUTANT", "name": "Rat mutant", "hp": 12, "atk": 4},
    {"id": "PUMA", "name": "Puma", "hp": 14, "atk": 5},
    {"id": "VOYOU", "name": "Voyou", "hp": 11, "atk": 4},
]

SCENES = [
    "Une ruelle de Davis sent la poudre et le ketchup renversé. Mikasa plisse les yeux.",
    "Une porte de service claque à Strawberry. L’air goûte la fuite et les ennuis.",
    "Un néon de Vespucci grésille. Quelque chose bouge derrière les poubelles.",
    "Downtown. Les vitrines reflètent ton visage… et une silhouette derrière toi.",
]

T_PLAYERS = "HUNT_PLAYERS"   # <-- adapte si ton onglet s'appelle autrement

def get_player_row(s: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """
    Retourne (row_index_sheet, player_dict) ou (None, None)
    row_index_sheet est la ligne Sheets (start=2 car header ligne 1).
    """
    rows = s.get_all_records(T_PLAYERS)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def ensure_player(
    s: SheetsService,
    *,
    discord_id: int,
    vip_code: str,
    pseudo: str,
    is_employee: bool = False
) -> Tuple[int, Dict[str, Any]]:
    """
    Crée le player s'il n'existe pas.
    Colonnes attendues minimales dans HUNT_PLAYERS:
    discord_id, vip_code, pseudo, is_employee, hp, hp_max, xp, xp_total,
    hunt_dollars, inventory_json, state_json, last_daily_date, updated_at, created_at
    """
    row_i, row = get_player_row(s, discord_id)
    if row_i and row:
        return row_i, row

    payload = {
        "discord_id": str(discord_id),
        "vip_code": str(vip_code),
        "pseudo": str(pseudo),
        "is_employee": "1" if is_employee else "0",
        "hp": 100,
        "hp_max": 100,
        "xp": 0,
        "xp_total": 0,
        "hunt_dollars": 0,
        "inventory_json": "{}",
        "state_json": "",          # <- on va s'en servir pour le daily robuste
        "last_daily_date": "",
        "total_runs": 0,
        "updated_at": now_iso(),
        "created_at": now_iso(),
    }
    s.append_by_headers(T_PLAYERS, payload)

    row_i2, row2 = get_player_row(s, discord_id)
    if not row_i2 or not row2:
        raise RuntimeError("ensure_player: impossible de relire la ligne créée.")
    return row_i2, row2
# ==========================================================
# PLAYER HELPERS (alignés sur hs.ensure_player)
# ==========================================================
def ensure_player_profile(
    sheets,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    is_employee: bool,
) -> Tuple[int, Dict[str, Any]]:
    return hs.ensure_player(
        sheets,
        discord_id=int(discord_id),
        vip_code=normalize_code(code_vip),
        pseudo=display_name(pseudo),
        is_employee=bool(is_employee),
    )

def set_avatar(
    sheets,
    *,
    discord_id: int,
    avatar_tag: str,
    avatar_url: str,
) -> Tuple[bool, str]:
    row_i, row = hs.get_player_row(sheets, int(discord_id))
    if not row_i or not row:
        return False, "Profil HUNT introuvable."
    hs.player_set_avatar(sheets, int(row_i), tag=(avatar_tag or "").strip().upper(), url=(avatar_url or "").strip())
    return True, ""

def try_assign_permanent_ally(sheets, p_row_i: int, player: Dict[str, Any]) -> bool:
    """
    Donne un allié UNE FOIS (permanent) :
    - seulement si pas d'allié déjà
    - roll 50% si is_employee
    - roll 10% sinon
    - jamais le même que l'avatar_tag
    - mémorise le roll dans equipped_json.meta.ally_roll_done
    """
    ally_tag = str(player.get("ally_tag", "") or "").strip().upper()
    if ally_tag:
        return False

    if bool(hs.meta_get(player, "ally_roll_done", False)):
        return False

    is_emp = str(player.get("is_employee", "")).strip().lower() in ("1", "true", "yes", "y", "on")
    chance = 0.50 if is_emp else 0.10

    # on marque "déjà tenté" quoi qu'il arrive (anti spam)
    hs.meta_set(sheets, int(p_row_i), player, "ally_roll_done", True)

    if random.random() > chance:
        return False

    avatar_tag = str(player.get("avatar_tag", "") or "").strip().upper()
    ally = hda.pick_ally(exclude_tag=avatar_tag)

    hs.player_set_ally(sheets, int(p_row_i), ally_tag=ally.tag, ally_url=ally.image)

    hs.log(
        sheets,
        discord_id=int(player.get("discord_id", 0) or 0),
        code_vip=str(player.get("code_vip", "") or ""),
        kind="ALLY",
        message=f"ally assigned {ally.tag}",
        meta={"ally_tag": ally.tag, "chance": chance, "is_employee": is_emp},
    )
    return True

# ==========================================================
# JAIL
# ==========================================================
def apply_jail_to_player(
    sheets,
    *,
    player_row_i: int,
    discord_id: int,
    code_vip: str,
    hours: float,
    reason: str,
) -> datetime:
    until = hs.set_jail(
        sheets,
        discord_id=int(discord_id),
        hours=float(hours),
        reason=str(reason or ""),
        code_vip=str(code_vip or ""),
    )
    return until

# ==========================================================
# DAILY STATE (multi-tours)
# ==========================================================
def _player_stat_int(player: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(player.get(key, default) or default)
    except Exception:
        return default

def new_daily_state(player: Dict[str, Any]) -> Dict[str, Any]:
    enemy = random.choice(ENEMIES)
    hp_max = _player_stat_int(player, "stats_hp", 30)

    return {
        "scene": random.choice(SCENES),
        "turn": 1,

        "player_hp": hp_max,
        "player_hp_max": hp_max,

        "enemy": {
            "id": enemy["id"],
            "name": enemy["name"],
            "hp": int(enemy["hp"]),
            "hp_max": int(enemy["hp"]),
            "atk": int(enemy["atk"]),
        },

        "log": [],
        "done": False,

        "reward_xp": 0,
        "reward_dollars": 0,

        "died": False,
        "jailed": False,
        "jail_hours": 0.0,
    }

def _append_log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("log", [])
    state["log"].append((msg or "")[:400])

def _reward_money() -> int:
    return random.randint(15, 45)

def _reward_xp() -> int:
    return random.randint(8, 20)

def apply_enemy_turn(state: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    df = _player_stat_int(player, "stats_def", 2)

    roll = d20()
    raw = int(state["enemy"]["atk"]) + (1 if roll >= 16 else 0)
    dmg = max(0, raw - df)

    state["player_hp"] = max(0, int(state["player_hp"]) - dmg)
    _append_log(state, f"🐾 Riposte **{state['enemy']['name']}**: jet **{roll}** → tu prends **{dmg}** dégâts.")

    if state["player_hp"] <= 0:
        state["done"] = True
        state["died"] = True
        state["reward_dollars"] = max(0, int(state["reward_dollars"]) - random.randint(5, 15))
        state["reward_xp"] = max(0, int(state["reward_xp"]) - 1)
        _append_log(state, "💀 Tu t’écroules. Mikasa te tire hors du danger… et te juge silencieusement.")
    else:
        state["turn"] = int(state.get("turn", 1)) + 1

    return state

def apply_attack(state: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    atk = _player_stat_int(player, "stats_atk", 3)

    roll = d20()
    dmg = max(1, atk + (1 if roll >= 15 else 0) - (1 if roll <= 4 else 0))
    if roll == 20:
        dmg += 3

    state["enemy"]["hp"] = max(0, int(state["enemy"]["hp"]) - dmg)
    _append_log(state, f"🗡️ Jet d’attaque: **{roll}** → tu infliges **{dmg}** dégâts.")

    if state["enemy"]["hp"] <= 0:
        state["done"] = True
        bonus = d20()
        dollars = _reward_money() + (bonus // 4)
        xp = (_reward_xp() // 3) + (1 if bonus >= 15 else 0)

        state["reward_dollars"] += int(dollars)
        state["reward_xp"] += int(xp)

        _append_log(state, f"🏁 Ennemi vaincu. Récompenses: **+{dollars} Hunt$**, **+{xp} XP**.")
        return state

    return apply_enemy_turn(state, player)

def apply_heal(state: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    roll = d20()
    heal = 3 + (2 if roll >= 15 else 0)
    state["player_hp"] = min(int(state["player_hp_max"]), int(state["player_hp"]) + heal)
    _append_log(state, f"🩹 Tu te soignes: jet **{roll}** → **+{heal} PV**.")
    return apply_enemy_turn(state, player)

def apply_steal(state: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    cha = _player_stat_int(player, "stats_cha", 2)
    luck = _player_stat_int(player, "stats_luck", 1)
    roll = d20()
    score = roll + cha + luck

    if score >= 18:
        gain = 15 + (roll // 3)
        state["reward_dollars"] += int(gain)
        _append_log(state, f"👜 Vol réussi: jet **{roll}** → **+{gain} Hunt$**. Personne n’a rien vu… presque.")
        return apply_enemy_turn(state, player)

    hours = 2 + max(0, (18 - score)) * 0.75
    hours = min(float(hs.MAX_JAIL_HOURS), float(hours))

    state["done"] = True
    state["jailed"] = True
    state["jail_hours"] = float(hours)
    _append_log(state, f"🚨 Vol raté: jet **{roll}** → menottes. **Prison {hours:.1f}h**.")
    return state

# ==========================================================
# DAILY FLOW
# ==========================================================
def start_or_resume_daily(
    sheets,
    *,
    player_row: Dict[str, Any],
) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    discord_id = int(player_row.get("discord_id", 0) or 0)
    code_vip = normalize_code(str(player_row.get("code_vip", "") or ""))

    date_key = hs.date_key_fr()
    daily_row_i, daily_row = hs.ensure_daily(
        sheets,
        discord_id=discord_id,
        code_vip=code_vip,
        date_key=date_key,
    )

    state = hs.json_loads_safe(daily_row.get("state_json", ""), {})
    if not state:
        state = new_daily_state(player_row)
        hs.save_daily_state(sheets, int(daily_row_i), step=0, state=state)

    return int(daily_row_i), daily_row, state

def apply_choice_and_persist(
    sheets,
    *,
    player_row_i: int,
    player_row: Dict[str, Any],
    daily_row_i: int,
    state: Dict[str, Any],
    choice: str,  # "ATTACK" | "HEAL" | "STEAL"
) -> Dict[str, Any]:
    if state.get("done"):
        return state

    c = (choice or "").strip().upper()
    if c == "HEAL":
        state = apply_heal(state, player_row)
    elif c == "STEAL":
        state = apply_steal(state, player_row)
    else:
        state = apply_attack(state, player_row)

    step = int(state.get("turn", 1))
    hs.save_daily_state(sheets, int(daily_row_i), step=step, state=state)

    if state.get("done"):
        finalize_daily_run(
            sheets,
            player_row_i=int(player_row_i),
            player_row=player_row,
            daily_row_i=int(daily_row_i),
            state=state,
        )
    return state

def finalize_daily_run(
    sheets,
    *,
    player_row_i: int,
    player_row: Dict[str, Any],
    daily_row_i: int,
    state: Dict[str, Any],
) -> None:
    discord_id = int(player_row.get("discord_id", 0) or 0)
    code_vip = normalize_code(str(player_row.get("code_vip", "") or ""))

    died = bool(state.get("died"))
    jailed = bool(state.get("jailed"))
    jail_hours = float(state.get("jail_hours", 0) or 0)

    earned_xp = int(state.get("reward_xp", 0) or 0)
    earned_dol = int(state.get("reward_dollars", 0) or 0)

    # jail + heat
    if jailed and jail_hours > 0:
        hs.set_jail(
            sheets,
            discord_id=discord_id,
            hours=min(float(hs.MAX_JAIL_HOURS), float(jail_hours)),
            reason="STEAL_FAIL",
            code_vip=code_vip,
        )
        # heat +10
        try:
            heat = int(player_row.get("heat", 0) or 0)
        except Exception:
            heat = 0
        heat = min(100, heat + 10)
        sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "heat", str(int(heat)))

    # add money/xp
    cur_d = hs.player_money_get(player_row)
    try:
        cur_xp = int(player_row.get("xp", 0) or 0)
    except Exception:
        cur_xp = 0
    try:
        cur_xpt = int(player_row.get("xp_total", 0) or 0)
    except Exception:
        cur_xpt = 0

    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "hunt_dollars", str(max(0, cur_d + earned_dol)))
    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "xp", str(max(0, cur_xp + earned_xp)))
    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "xp_total", str(max(0, cur_xpt + earned_xp)))

    # runs/deaths
    try:
        total_runs = int(player_row.get("total_runs", 0) or 0)
    except Exception:
        total_runs = 0
    try:
        total_deaths = int(player_row.get("total_deaths", 0) or 0)
    except Exception:
        total_deaths = 0

    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "total_runs", str(int(total_runs + 1)))
    if died:
        sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "total_deaths", str(int(total_deaths + 1)))

    # daily lock
    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "last_daily_date", hs.date_key_fr())
    sheets.update_cell_by_header(hs.T_PLAYERS, int(player_row_i), "updated_at", now_iso())

    summary = "💀 Défaite" if died else ("🚨 Prison" if jailed else "🏁 Victoire")

    hs.finish_daily(
        sheets,
        int(daily_row_i),
        summary=summary,
        xp=earned_xp,
        dollars=earned_dol,
        dmg=0,
        died=died,
        jailed=jailed,
    )

    hs.hunt_log(
        sheets,
        discord_id=discord_id,
        code_vip=code_vip,
        kind="DAILY_DONE",
        message=f"{summary} | +{earned_dol} Hunt$ | +{earned_xp} XP",
    )

# ==========================================================
# KEY CLAIM (staff)
# ==========================================================
def staff_claim_key_for_vip(
    sheets,
    *,
    code_vip: str,
    target_discord_id: int,
    claimed_by_staff_id: int,
    is_employee: bool,
) -> Tuple[bool, str]:
    key_type = "GOLD" if is_employee else "NORMAL"
    return hs.claim_weekly_key(
        sheets,
        code_vip=normalize_code(code_vip),
        discord_id=int(target_discord_id),
        claimed_by=int(claimed_by_staff_id),
        key_type=key_type,
    )

# ==========================================================
# LOOT OPEN KEY (depuis HUNT_ITEMS)
# ==========================================================
RARITY_WEIGHTS_NORMAL = {"common": 55, "uncommon": 30, "rare": 12, "epic": 3, "legendary": 0}
RARITY_WEIGHTS_GOLD   = {"common": 20, "uncommon": 50, "rare": 22, "epic": 7, "legendary": 1}

DEFAULT_QTY_BY_TYPE = {
    "consumable": (1, 2),
    "weapon": (1, 1),
    "armor": (1, 1),
    "key": (1, 1),
    "misc": (1, 3),
}

def _norm_rarity(r: str) -> str:
    r = (r or "").strip().lower()
    if r in ("commun", "common"): return "common"
    if r in ("peu commun", "uncommon"): return "uncommon"
    if r == "rare": return "rare"
    if r in ("epic", "épique"): return "epic"
    if r in ("legendary", "légendaire"): return "legendary"
    return "common"

def loot_pick_item(items: List[Dict[str, Any]], *, is_gold: bool) -> Dict[str, Any]:
    weights = RARITY_WEIGHTS_GOLD if is_gold else RARITY_WEIGHTS_NORMAL
    pool: List[Tuple[Dict[str, Any], int]] = []

    for it in items or []:
        iid = str(it.get("item_id", "")).strip()
        if not iid:
            continue
        rarity = _norm_rarity(str(it.get("rarity", "")))
        w = int(weights.get(rarity, 0))
        if w > 0:
            pool.append((it, w))

    if not pool:
        candidates = [it for it in (items or []) if str(it.get("item_id", "")).strip()]
        return random.choice(candidates) if candidates else {}

    total = sum(w for _, w in pool)
    pick = random.randint(1, total)
    acc = 0
    for it, w in pool:
        acc += w
        if pick <= acc:
            return it
    return pool[-1][0]

def loot_compute_qty(item: Dict[str, Any]) -> int:
    typ = str(item.get("type", "") or "").strip().lower() or "misc"
    lo, hi = DEFAULT_QTY_BY_TYPE.get(typ, (1, 1))
    rarity = _norm_rarity(str(item.get("rarity", "")))

    if typ in ("consumable", "misc"):
        if rarity == "common":
            hi = max(hi, hi + 1)
        elif rarity in ("epic", "legendary"):
            lo, hi = 1, 1

    return max(1, random.randint(int(lo), int(hi)))

def loot_open_key(items: List[Dict[str, Any]], *, key_type: str) -> Dict[str, Any]:
    kt = (key_type or "").strip().lower()
    is_gold = (kt == "gold_key")

    it = loot_pick_item(items, is_gold=is_gold)
    if not it:
        return {"item_id": "", "item_name": "", "qty": 0, "rarity": "", "key_type": kt}

    iid = str(it.get("item_id", "")).strip()
    name = str(it.get("name", "")).strip() or iid
    rarity = _norm_rarity(str(it.get("rarity", "")))
    qty = loot_compute_qty(it)

    return {"item_id": iid, "item_name": name, "qty": int(qty), "rarity": rarity, "key_type": kt}

# ==========================================================
# Weekly ranks recompute (sans helper manquant)
# ==========================================================
def weekly_score(row: dict) -> int:
    def gi(k):
        try: return int(row.get(k, 0) or 0)
        except Exception: return 0
    wins = gi("wins")
    good = gi("good_runs")
    deaths = gi("deaths")
    jail = gi("jail_count")
    boss = gi("boss_kills")
    steals = gi("steals")
    dol = gi("earned_dollars")
    xp = gi("earned_xp")
    return (
        10*wins + 2*good - 6*deaths - 3*jail + 8*boss + 4*steals + (dol // 200) + (xp // 50)
    )

def weekly_recompute_ranks(sheets, week_key: str) -> None:
    rows = sheets.get_all_records(hs.T_WEEKLY) or []
    wk = [r for r in rows if str(r.get("week_key", "")).strip() == str(week_key).strip()]
    for r in wk:
        r["__score"] = weekly_score(r)

    wk.sort(key=lambda r: (-int(r["__score"]), str(r.get("pseudo", ""))))

    for rank, r in enumerate(wk, start=1):
        did = int(r.get("discord_id", 0) or 0)
        row_i, row = hs.weekly_find_row(sheets, str(week_key).strip(), did)
        if not row_i or not row:
            continue
        sheets.update_cell_by_header(hs.T_WEEKLY, int(row_i), "score", str(int(r["__score"])))
        sheets.update_cell_by_header(hs.T_WEEKLY, int(row_i), "top_rank", str(int(rank)))
        sheets.update_cell_by_header(hs.T_WEEKLY, int(row_i), "updated_at", now_iso())

# ==========================================================
# ENTRYPOINTS
# ==========================================================
def can_player_start_daily(player_row: Dict[str, Any]) -> Tuple[bool, str]:
    return hs.can_run_daily(player_row)

def start_daily_if_allowed(
    sheets,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    is_employee: bool,
) -> Tuple[bool, str, Optional[int], Optional[Dict[str, Any]], Optional[int], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    player_row_i, player_row = ensure_player_profile(
        sheets,
        discord_id=int(discord_id),
        code_vip=str(code_vip),
        pseudo=str(pseudo),
        is_employee=bool(is_employee),
    )

    ok, msg = hs.can_run_daily(player_row)
    if not ok:
        return False, msg, player_row_i, player_row, None, None, None

    daily_row_i, daily_row, state = start_or_resume_daily(sheets, player_row=player_row)
    return True, "OK", player_row_i, player_row, daily_row_i, daily_row, state
