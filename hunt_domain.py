# hunt_domain.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
from datetime import datetime, timedelta
import random

import hunt_services as hs
from services import now_fr, now_iso, normalize_code, display_name

from hunt_data import rarity_rank

EQUIP_SLOTS = {
    "weapon": "weapon",
    "armor": "armor",
}

# ==========================================================
# AVATARS (Direction SubUrban)
# IMPORTANT: tes URLs GitHub doivent être en "raw" pour marcher en thumbnail Discord.
# Exemple:
# https://raw.githubusercontent.com/<user>/<repo>/<branch>/Mai.png
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
# (on enrichira ensuite + boss + dialogues)
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


# ==========================================================
# PLAYER HELPERS (alignés sur HUNT_PLAYERS)
# ==========================================================
def ensure_player_profile(
    sheets,
    *,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    is_employee: bool,
) -> Tuple[int, Dict[str, Any]]:
    """
    Crée/MAJ le joueur (ligne HUNT_PLAYERS) avec les bons headers.
    """
    return hs.upsert_player(
        sheets,
        discord_id=discord_id,
        code_vip=normalize_code(code_vip),
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
    row_i, row = hs.find_player_row(sheets, discord_id)
    if not row_i or not row:
        return False, "Profil HUNT introuvable."

    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "avatar_tag", (avatar_tag or "").strip().upper())
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "avatar_url", (avatar_url or "").strip())
    sheets.update_cell_by_header(hs.T_PLAYERS, row_i, "updated_at", now_iso())
    return True, ""


# ==========================================================
# JAIL (12h max)
# ==========================================================
def apply_jail_to_player(
    sheets,
    *,
    player_row_i: int,
    hours: float,
    reason: str,
) -> datetime:
    h = max(0.25, float(hours))
    h = min(float(hs.MAX_JAIL_HOURS), h)

    until = now_fr() + timedelta(seconds=int(h * 3600))
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "jail_until", until.astimezone(hs.PARIS_TZ).isoformat(timespec="seconds"))
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "updated_at", now_iso())

    # log
    try:
        hs.hunt_log(
            sheets,
            discord_id=int(sheets.get_all_records(hs.T_PLAYERS)[player_row_i-2].get("discord_id", "0") or 0),
            code_vip=str(sheets.get_all_records(hs.T_PLAYERS)[player_row_i-2].get("code_vip", "") or ""),
            kind="JAIL",
            message=f"Prison {h:.2f}h | {reason}",
        )
    except Exception:
        pass

    return until


# ==========================================================
# DAILY STATE (multi-tours)
# On sauvegarde à chaque action (anti retour arrière).
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
        "jail_hours": 0,
    }


def _append_log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("log", [])
    state["log"].append(msg[:400])


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

        # mort = perte partielle (soft)
        # On évite de casser le fun: on retire un peu de Hunt$ et un peu d'XP gagnée dans la run.
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
        dollars = hs.money_reward() + (bonus // 4)
        xp = hs.xp_reward() // 3 + (1 if bonus >= 15 else 0)

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
    """
    Vol = gain Hunt$ mais risque prison.
    """
    cha = _player_stat_int(player, "stats_cha", 2)
    luck = _player_stat_int(player, "stats_luck", 1)
    roll = d20()
    score = roll + cha + luck

    if score >= 18:
        gain = 15 + (roll // 3)
        state["reward_dollars"] += int(gain)
        _append_log(state, f"👜 Vol réussi: jet **{roll}** → **+{gain} Hunt$**. Personne n’a rien vu… presque.")
        # l’ennemi peut quand même te tomber dessus après ton vol
        return apply_enemy_turn(state, player)

    # prison: 2h -> 12h (max)
    hours = 2 + max(0, (18 - score)) * 0.75
    hours = min(float(hs.MAX_JAIL_HOURS), hours)

    state["done"] = True
    state["jailed"] = True
    state["jail_hours"] = float(hours)
    _append_log(state, f"🚨 Vol raté: jet **{roll}** → menottes. **Prison {hours:.1f}h**.")
    return state


# ==========================================================
# DAILY FLOW (création / reprise / sauvegarde / finish)
# ==========================================================
def start_or_resume_daily(
    sheets,
    *,
    player_row: Dict[str, Any],
) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    """
    Retourne: (daily_row_i, daily_row, state_dict)
    - crée une ligne HUNT_DAILY si besoin
    - charge state_json si déjà running
    """
    discord_id = int(player_row.get("discord_id", 0) or 0)
    code_vip = normalize_code(str(player_row.get("code_vip", "") or ""))

    date_key = hs.date_key_fr()
    daily_row_i, daily_row = hs.ensure_daily(
        sheets,
        discord_id=discord_id,
        code_vip=code_vip,
        date_key=date_key,
    )

    state = hs.json_loads_safe(str(daily_row.get("state_json", "") or ""), {})
    if not state:
        state = new_daily_state(player_row)
        hs.save_daily_state(sheets, daily_row_i, step=0, state=state)

    return daily_row_i, daily_row, state


def apply_choice_and_persist(
    sheets,
    *,
    player_row_i: int,
    player_row: Dict[str, Any],
    daily_row_i: int,
    state: Dict[str, Any],
    choice: str,  # "ATTACK" | "HEAL" | "STEAL"
) -> Dict[str, Any]:
    """
    Applique un choix de tour, puis sauvegarde immédiatement state_json + step.
    """
    if state.get("done"):
        return state

    c = (choice or "").strip().upper()
    if c == "HEAL":
        state = apply_heal(state, player_row)
    elif c == "STEAL":
        state = apply_steal(state, player_row)
    else:
        state = apply_attack(state, player_row)

    # persist
    step = int(state.get("turn", 1))
    hs.save_daily_state(sheets, daily_row_i, step=step, state=state)

    # if done -> finalize
    if state.get("done"):
        finalize_daily_run(
            sheets,
            player_row_i=player_row_i,
            player_row=player_row,
            daily_row_i=daily_row_i,
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
    """
    Met à jour:
    - HUNT_DAILY DONE
    - HUNT_PLAYERS (dollars/xp/last_daily_date/jail_until/heat/runs/deaths)
    """
    discord_id = int(player_row.get("discord_id", 0) or 0)
    code_vip = normalize_code(str(player_row.get("code_vip", "") or ""))

    died = bool(state.get("died"))
    jailed = bool(state.get("jailed"))
    jail_hours = float(state.get("jail_hours", 0) or 0)

    earned_xp = int(state.get("reward_xp", 0) or 0)
    earned_dol = int(state.get("reward_dollars", 0) or 0)

    # Apply jail if needed
    if jailed and jail_hours > 0:
        until = now_fr() + timedelta(seconds=int(min(float(hs.MAX_JAIL_HOURS), jail_hours) * 3600))
        sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "jail_until", until.astimezone(hs.PARIS_TZ).isoformat(timespec="seconds"))

        # heat +10 si vol raté (simple)
        try:
            heat = int(player_row.get("heat", 0) or 0)
        except Exception:
            heat = 0
        heat = min(100, heat + 10)
        sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "heat", heat)

    # Add dollars/xp
    try:
        cur_d = int(player_row.get("hunt_dollars", 0) or 0)
    except Exception:
        cur_d = 0
    try:
        cur_xp = int(player_row.get("xp", 0) or 0)
    except Exception:
        cur_xp = 0
    try:
        cur_xpt = int(player_row.get("xp_total", 0) or 0)
    except Exception:
        cur_xpt = 0

    new_d = max(0, cur_d + earned_dol)
    new_xp = max(0, cur_xp + earned_xp)
    new_xpt = max(0, cur_xpt + earned_xp)

    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "hunt_dollars", new_d)
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "xp", new_xp)
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "xp_total", new_xpt)

    # runs / deaths
    try:
        total_runs = int(player_row.get("total_runs", 0) or 0)
    except Exception:
        total_runs = 0
    try:
        total_deaths = int(player_row.get("total_deaths", 0) or 0)
    except Exception:
        total_deaths = 0

    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "total_runs", total_runs + 1)
    if died:
        sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "total_deaths", total_deaths + 1)

    # daily lock
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "last_daily_date", hs.date_key_fr())
    sheets.update_cell_by_header(hs.T_PLAYERS, player_row_i, "updated_at", now_iso())

    # daily summary
    summary = ""
    if died:
        summary = "💀 Défaite"
    elif jailed:
        summary = "🚨 Prison"
    else:
        summary = "🏁 Victoire"

    hs.finish_daily(
        sheets,
        daily_row_i,
        summary=summary,
        xp=earned_xp,
        dollars=earned_dol,
        dmg=int(state.get("dmg_taken", 0) or 0),
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
    """
    /hunt key claim <VIP_ID>
    - 1 clé / semaine / VIP
    - employé => GOLD, sinon NORMAL
    """
    key_type = "GOLD" if is_employee else "NORMAL"
    return hs.claim_weekly_key(
        sheets,
        code_vip=normalize_code(code_vip),
        discord_id=int(target_discord_id),
        claimed_by=int(claimed_by_staff_id),
        key_type=key_type,
    )


def is_equippable(item: Dict[str, Any]) -> bool:
    t = str(item.get("type", "")).strip().lower()
    return t in ("weapon", "armor")

def equip_slot(item: Dict[str, Any]) -> Optional[str]:
    t = str(item.get("type", "")).strip().lower()
    return EQUIP_SLOTS.get(t)

def loot_pick_from_items(items: List[Dict[str, Any]], *, key_type: str) -> Tuple[str, int, str, str]:
    """
    Retourne (item_id, qty, rarity, name)
    key_type: "key" ou "gold_key"
    """
    # pool = items avec item_id
    pool = [it for it in items if str(it.get("item_id", "")).strip()]
    if not pool:
        return ("", 0, "common", "")

    # poids rarité
    # normal: beaucoup common/uncommon
    # gold: plus de rare/epic
    if key_type == "gold_key":
        weights = {"common": 35, "uncommon": 35, "rare": 18, "epic": 10, "legendary": 2}
    else:
        weights = {"common": 55, "uncommon": 30, "rare": 12, "epic": 3, "legendary": 0}

    def w(it: Dict[str, Any]) -> int:
        r = str(it.get("rarity", "common")).strip().lower()
        return int(weights.get(r, 1))

    chosen = random.choices(pool, weights=[w(it) for it in pool], k=1)[0]
    iid = str(chosen.get("item_id", "")).strip()
    name = str(chosen.get("name", iid)).strip()
    rarity = str(chosen.get("rarity", "common")).strip().lower()

    # qty par rarity (simple)
    if rarity in ("legendary", "epic"):
        qty = 1
    elif rarity == "rare":
        qty = random.choice([1, 1, 2])
    else:
        qty = random.choice([1, 2])

    return (iid, qty, rarity, name)

# ==========================================================
# ENTRYPOINTS “COMMAND LOGIC” (utiles côté bot)
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
    """
    Retourne:
    ok, msg,
    player_row_i, player_row,
    daily_row_i, daily_row,
    state
    """
    player_row_i, player_row = ensure_player_profile(
        sheets,
        discord_id=discord_id,
        code_vip=code_vip,
        pseudo=pseudo,
        is_employee=is_employee,
    )

    ok, msg = hs.can_run_daily(player_row)
    if not ok:
        return False, msg, player_row_i, player_row, None, None, None

    daily_row_i, daily_row, state = start_or_resume_daily(sheets, player_row=player_row)
    return True, "OK", player_row_i, player_row, daily_row_i, daily_row, state

RARITY_WEIGHTS_NORMAL = {
    "common": 70,
    "uncommon": 24,
    "rare": 5,
    "epic": 1,
    "legendary": 0,
}

RARITY_WEIGHTS_GOLD = {
    "common": 20,
    "uncommon": 50,
    "rare": 22,
    "epic": 7,
    "legendary": 1,
}

# qty par type (par défaut)
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
    if r in ("rare",): return "rare"
    if r in ("epic", "épique"): return "epic"
    if r in ("legendary", "légendaire"): return "legendary"
    return "common"

def loot_pick_item(items: List[Dict[str, Any]], *, is_gold: bool, rng: Optional[random.Random] = None) -> Dict[str, Any]:
    rng = rng or random.Random()
    weights = RARITY_WEIGHTS_GOLD if is_gold else RARITY_WEIGHTS_NORMAL

    pool: List[Tuple[Dict[str, Any], int]] = []
    for it in items or []:
        iid = str(it.get("item_id", "")).strip()
        if not iid:
            continue
        rarity = _norm_rarity(str(it.get("rarity", "")))
        w = int(weights.get(rarity, 0))
        if w <= 0:
            continue
        pool.append((it, w))

    # fallback si ton sheet n’a pas encore de raretés propres
    if not pool:
        # prend n’importe quel item_id non vide
        candidates = [it for it in items if str(it.get("item_id", "")).strip()]
        if not candidates:
            return {}
        return rng.choice(candidates)

    total = sum(w for _, w in pool)
    pick = rng.randint(1, total)
    acc = 0
    for it, w in pool:
        acc += w
        if pick <= acc:
            return it
    return pool[-1][0]

def loot_compute_qty(item: Dict[str, Any], *, rng: Optional[random.Random] = None) -> int:
    rng = rng or random.Random()
    typ = str(item.get("type", "") or "").strip().lower() or "misc"
    lo, hi = DEFAULT_QTY_BY_TYPE.get(typ, (1, 1))

    rarity = _norm_rarity(str(item.get("rarity", "")))
    # petit bonus qty sur commun/uncommon
    if typ in ("consumable", "misc"):
        if rarity == "common":
            hi = max(hi, hi + 1)
        elif rarity == "uncommon":
            hi = max(hi, hi)
        elif rarity in ("epic", "legendary"):
            lo, hi = 1, 1

    return max(1, rng.randint(int(lo), int(hi)))

def loot_open_key(items: List[Dict[str, Any]], *, key_type: str) -> Dict[str, Any]:
    """
    Retour:
    {
      item_id, item_name, qty, rarity, key_type
    }
    """
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

# -------------------------------------------------
# CONSUMABLE EFFECTS
# -------------------------------------------------

def consumable_apply(player: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applique les effets d’un consommable sur le player.
    Retour:
    {
      healed: int,
      msg: str
    }
    """
    power = {}
    try:
        raw = item.get("power_json", "")
        if isinstance(raw, dict):
            power = raw
        else:
            power = json.loads(raw) if raw else {}
    except Exception:
        power = {}

    healed = 0
    msg = "Effet appliqué."

    # HEAL
    if "heal" in power:
        try:
            heal = int(power.get("heal", 0))
        except Exception:
            heal = 0

        hp = int(player.get("stats_hp", 0) or 0)
        max_hp = hp  # pour l’instant hp = max_hp (tu ajouteras plus tard stats_max_hp)

        healed = heal
        msg = f"Soigne **{heal} HP**."

    return {"healed": healed, "msg": msg}
