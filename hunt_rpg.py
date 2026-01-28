# hunt_domain.py (RPG daily robust core)
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple, List
import json, uuid, random
from services import SheetsService, now_iso, now_fr

T_PLAYERS = "HUNT_PLAYERS"     # adapte
T_DAILIES = "HUNT_DAILIES"     # adapte

# ---------------------------
# Utils state_json
# ---------------------------
def _safe_load_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

def _dump_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def get_player_row(s: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = s.get_all_records(T_PLAYERS)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def update_player_state_json(s: SheetsService, row_i: int, state: dict):
    s.update_cell_by_header(T_PLAYERS, row_i, "state_json", _dump_json(state))
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def clear_player_state_json(s: SheetsService, row_i: int):
    s.update_cell_by_header(T_PLAYERS, row_i, "state_json", "")
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def today_key(dt=None) -> str:
    dt = dt or now_fr()
    return dt.strftime("%Y-%m-%d")

# ---------------------------
# Arc logic (simple)
# ---------------------------
ARC_1 = "ARC_OMBRES"   # Attenin
ARC_2 = "ARC_LUXUS"
ARC_3 = "ARC_DODO"
ARC_4 = "ARC_SHAKIR"

def arc_for_player(player: dict) -> str:
    try:
        xp_total = int(player.get("xp_total", 0) or 0)
    except Exception:
        xp_total = 0

    if xp_total < 250:
        return ARC_1
    if xp_total < 600:
        return ARC_2
    if xp_total < 1100:
        return ARC_3
    return ARC_4

# ---------------------------
# Landscapes & encounters
# Tu branches ici tes "paysages"
# ---------------------------
LANDSCAPES_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["docks_brumeux", "neon_alley", "ruelle_sale", "parking_sombre"],
    ARC_2: ["quartier_luxe", "casino_floor", "hotel_rooftop", "galerie_art"],
    ARC_3: ["atelier", "backroom", "entrepot", "rue_industrielle"],
    ARC_4: ["club_backstage", "arena", "studio_clip", "toit_sous_neons"],
}

ENCOUNTERS_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["voyou", "chien_errant", "rat_mutant", "coyote"],
    ARC_2: ["garde_prive", "arnaqueur", "chasseur_de_primes", "drone_surveillance"],
    ARC_3: ["rival", "saboteur", "flic_corrompu", "membre_gang"],
    ARC_4: ["fanatique", "bodyguard", "sniper", "meute_urbaine"],
}

MICROBOSSES_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["Veilleur des Docks", "Mère des Chiens", "Rôdeur au Néon"],
    ARC_2: ["Microboss Luxus A", "Microboss Luxus B", "Microboss Luxus C"],
    ARC_3: ["Microboss Dodo A", "Microboss Dodo B"],
    ARC_4: ["Microboss Shakir A", "Microboss Shakir B"],
}

BOSS_BY_ARC: Dict[str, str] = {
    ARC_1: "ATTENIN",
    ARC_2: "LUXUS",
    ARC_3: "DODO",
    ARC_4: "SHAKIR",
}

def _rng_for_daily(discord_id: int, date_key: str) -> random.Random:
    # stable, mais unique par joueur
    seed = f"{date_key}:{discord_id}"
    return random.Random(seed)

# ---------------------------
# Daily state machine
# ---------------------------
def daily_state_from_player(player: dict) -> dict:
    return _safe_load_json(str(player.get("state_json", "") or ""))

def daily_is_active(state: dict, date_key: str) -> bool:
    return bool(state and state.get("mode") == "daily" and state.get("date_key") == date_key)

def daily_begin_or_resume(
    s: SheetsService,
    *,
    discord_id: int,
    vip_code: str,
    pseudo: str,
) -> Tuple[int, Dict[str, Any], dict]:
    """
    Retourne (player_row_i, player_row, state)
    Crée ou reprend un daily en cours aujourd'hui.
    """
    row_i, player = get_player_row(s, discord_id)
    if not row_i or not player:
        raise RuntimeError("Player introuvable (get_player_row).")

    dk = today_key()
    state = daily_state_from_player(player)

    if daily_is_active(state, dk):
        # resume
        if not state.get("pending"):
            # si pending absent (corruption), on regénère
            state = daily_generate_pending(state, player, discord_id)
            update_player_state_json(s, row_i, state)
        return row_i, player, state

    # nouveau daily
    try:
        hp = int(player.get("hp", 100) or 100)
    except Exception:
        hp = 100
    try:
        hp_max = int(player.get("hp_max", 100) or 100)
    except Exception:
        hp_max = 100

    state = {
        "mode": "daily",
        "date_key": dk,
        "run_id": str(uuid.uuid4()),
        "step": 1,
        "max_steps": 3,
        "arc": arc_for_player(player),
        "hp": max(1, min(hp, hp_max)),
        "hp_max": hp_max,
        "log": [],
        "flags": {
            "microboss_kills": 0,
            "boss_killed": False,
        },
        "pending": None,
    }

    state = daily_generate_pending(state, player, discord_id)
    update_player_state_json(s, row_i, state)
    return row_i, player, state

def daily_generate_pending(state: dict, player: dict, discord_id: int) -> dict:
    dk = str(state.get("date_key"))
    arc = str(state.get("arc") or ARC_1)
    rnd = _rng_for_daily(discord_id, dk)

    # microboss chance (ex: 8%)
    micro_chance = 0.08
    is_micro = (rnd.random() < micro_chance)

    scene = rnd.choice(LANDSCAPES_BY_ARC.get(arc, ["rue"]))
    if is_micro:
        encounter = rnd.choice(MICROBOSSES_BY_ARC.get(arc, ["Microboss"]))
        kind = "MICROBOSS"
        difficulty = "HARD"
    else:
        encounter = rnd.choice(ENCOUNTERS_BY_ARC.get(arc, ["voyou"]))
        kind = "ENEMY"
        # difficulté simple: step 1 easy, step2 med, step3 hard
        step = int(state.get("step", 1) or 1)
        difficulty = "EASY" if step == 1 else ("MED" if step == 2 else "HARD")

    state["pending"] = {
        "scene": scene,
        "encounter": encounter,
        "kind": kind,
        "difficulty": difficulty,
    }
    return state

def _roll_2d20(discord_id: int, date_key: str, step: int, choice: str) -> Tuple[int, int]:
    # stable mais variable par choix & step
    rnd = random.Random(f"{date_key}:{discord_id}:{step}:{choice}")
    return rnd.randint(1, 20), rnd.randint(1, 20)

def daily_apply_choice(
    s: SheetsService,
    *,
    player_row_i: int,
    player: dict,
    state: dict,
    discord_id: int,
    choice: str,  # "explore"|"negotiate"|"fight"|"steal"
) -> Tuple[dict, dict]:
    """
    Applique un choix sur pending, met à jour state_json.
    Retourne (new_state, outcome)
    outcome = {result, text, hp_delta, money_delta, xp_delta, jail_hours, loot:[]}
    """
    dk = str(state.get("date_key"))
    step = int(state.get("step", 1) or 1)
    pending = state.get("pending") or {}
    arc = str(state.get("arc") or ARC_1)

    d1, d2 = _roll_2d20(discord_id, dk, step, choice)
    score = d1 + d2

    # base thresholds
    # EASY: 20, MED: 23, HARD: 26
    diff = str(pending.get("difficulty") or "MED").upper()
    target = 20 if diff == "EASY" else (23 if diff == "MED" else 26)

    win = score >= target

    # effets simples (tu pourras raffiner)
    hp = int(state.get("hp", 100) or 100)

    # risques selon choice
    jail_hours = 0
    hp_delta = 0

    if not win:
        # pénalité légère
        hp_delta = -random.randint(5, 14)
        if choice == "steal" and d1 <= 5:
            jail_hours = random.randint(2, 12)

    # gains
    base_money = 18 + step * 6
    base_xp = 10 + step * 5

    money_delta = base_money if win else max(5, base_money // 3)
    xp_delta = base_xp if win else max(2, base_xp // 3)

    # microboss reward boost
    if str(pending.get("kind")) == "MICROBOSS" and win:
        money_delta += 20
        xp_delta += 15
        try:
            state["flags"]["microboss_kills"] = int(state["flags"].get("microboss_kills", 0)) + 1
        except Exception:
            state.setdefault("flags", {})["microboss_kills"] = 1

    # HP clamp
    hp2 = max(1, min(int(state.get("hp_max", 100) or 100), hp + hp_delta))
    state["hp"] = hp2

    # log
    state.setdefault("log", []).append({
        "step": step,
        "scene": pending.get("scene"),
        "encounter": pending.get("encounter"),
        "kind": pending.get("kind"),
        "difficulty": diff,
        "choice": choice,
        "d20": [d1, d2],
        "target": target,
        "result": "WIN" if win else "LOSE",
        "hp_delta": hp_delta,
        "money_delta": money_delta,
        "xp_delta": xp_delta,
        "jail_hours": jail_hours,
    })

    # step progression
    step2 = step + 1
    state["step"] = step2

    finished = step2 > int(state.get("max_steps", 3) or 3)

    # regénère pending si pas fini
    if not finished:
        state["pending"] = None
        state = daily_generate_pending(state, player, discord_id)
        update_player_state_json(s, player_row_i, state)
    else:
        # finalize => on crédite player + log sheet + clear state
        outcome = daily_finalize(
            s,
            player_row_i=player_row_i,
            player=player,
            discord_id=discord_id,
            state=state
        )
        return {}, outcome  # state cleared (retourne vide)

    outcome = {
        "finished": False,
        "result": "WIN" if win else "LOSE",
        "score": score,
        "target": target,
        "hp": hp2,
        "hp_delta": hp_delta,
        "money_delta": money_delta,
        "xp_delta": xp_delta,
        "jail_hours": jail_hours,
        "pending_next": state.get("pending"),
    }
    return state, outcome

def daily_finalize(
    s: SheetsService,
    *,
    player_row_i: int,
    player: dict,
    discord_id: int,
    state: dict
) -> dict:
    """
    Crédite gains cumulés dans HUNT_PLAYERS + écrit une ligne HUNT_DAILIES
    + clear state_json
    """
    dk = str(state.get("date_key"))
    logs = state.get("log") or []

    total_money = sum(int(x.get("money_delta", 0) or 0) for x in logs)
    total_xp = sum(int(x.get("xp_delta", 0) or 0) for x in logs)
    jail_hours = max([int(x.get("jail_hours", 0) or 0) for x in logs] + [0])

    # lecture valeurs player
    def _i(v, d=0):
        try: return int(v or 0)
        except Exception: return d

    cur_money = _i(player.get("hunt_dollars", 0))
    cur_xp = _i(player.get("xp", 0))
    cur_xpt = _i(player.get("xp_total", 0))
    cur_runs = _i(player.get("total_runs", 0))
    hp_end = _i(state.get("hp", player.get("hp", 100)))

    # write player
    s.update_cell_by_header(T_PLAYERS, player_row_i, "hunt_dollars", cur_money + total_money)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "xp", cur_xp + total_xp)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "xp_total", cur_xpt + total_xp)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "hp", hp_end)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "last_daily_date", dk)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "total_runs", cur_runs + 1)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "updated_at", now_iso())

    # append daily log (simple)
    s.append_by_headers(T_DAILIES, {
        "date_key": dk,
        "discord_id": str(discord_id),
        "run_id": str(state.get("run_id")),
        "arc": str(state.get("arc")),
        "result": "DONE",
        "money_delta": total_money,
        "xp_delta": total_xp,
        "jail_delta_hours": jail_hours,
        "story": " | ".join([f"{x.get('choice')}:{x.get('encounter')}:{x.get('result')}" for x in logs])[:4500],
        "rewards_json": json.dumps({"steps": logs}, ensure_ascii=False),
        "created_at": now_iso(),
    })

    # clear state
    clear_player_state_json(s, player_row_i)

    return {
        "finished": True,
        "money_total": total_money,
        "xp_total": total_xp,
        "jail_hours": jail_hours,
        "hp_end": hp_end,
        "arc": str(state.get("arc")),
        "boss_next": BOSS_BY_ARC.get(str(state.get("arc")), ""),
    }
