# hunt_rpg.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import json, uuid, random
from datetime import timedelta

from services import SheetsService, now_fr, now_iso, PARIS_TZ

T_PLAYERS = "HUNT_PLAYERS"
T_DAILIES = "HUNT_DAILIES"  # si tu n'as pas encore l'onglet, tu peux commenter l'append plus bas

ENCOUNTER_IMAGES = {
  "Voyou": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Voyou.png",
  "Rat mutant": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Rat_Mutant.png",
  #"Luxus": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Luxus.png",
  #"Attenin": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Attenin.png",
  "Sanglier": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Sanglier.png",
  "Chien errant": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Chien_errant.png",
  #"Dodo Lasaumure": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Lasaumure.png",
  #"Shakir": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Shakir.png",
  "Coyotte": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Coyotte.png",
  #"Mike": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Mike.png",
  #"Clayton": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Clayton.png",
  "Puma": "https://raw.githubusercontent.com/immaimashiro/mikasa2-bot/main/Puma.png",
}

# ==========================================================
# JSON helpers (robustes)
# ==========================================================
def _safe_load_json(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

def _dump_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def today_key(dt=None) -> str:
    dt = dt or now_fr()
    return dt.strftime("%Y-%m-%d")

# ==========================================================
# Player access
# ==========================================================
def get_player_row(s: SheetsService, discord_id: int) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    rows = s.get_all_records(T_PLAYERS)
    for idx, r in enumerate(rows, start=2):
        if str(r.get("discord_id", "")).strip() == str(discord_id):
            return idx, r
    return None, None

def update_state(s: SheetsService, row_i: int, state: Dict[str, Any]) -> None:
    s.update_cell_by_header(T_PLAYERS, row_i, "state_json", _dump_json(state))
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def clear_state(s: SheetsService, row_i: int) -> None:
    s.update_cell_by_header(T_PLAYERS, row_i, "state_json", "")
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

# ==========================================================
# Prison / daily lock
# ==========================================================
def is_in_jail(player: Dict[str, Any]) -> Tuple[bool, str]:
    until = str(player.get("jail_until", "") or "").strip()
    if not until:
        return False, ""
    # On compare "en string" si tu stockes ISO, sinon tu peux parse.
    # Ici on fait simple : si jail_until existe, on considère in_jail
    # (tu peux raffiner avec parse_iso_dt si tu l'as).
    return True, until

def apply_jail(s: SheetsService, row_i: int, hours: int) -> None:
    dt = now_fr() + timedelta(hours=int(hours))
    s.update_cell_by_header(T_PLAYERS, row_i, "jail_until", dt.isoformat(timespec="seconds"))
    s.update_cell_by_header(T_PLAYERS, row_i, "updated_at", now_iso())

def daily_already_done(player: Dict[str, Any], date_key: str) -> bool:
    return str(player.get("last_daily_date", "") or "").strip() == str(date_key)

# ==========================================================
# Arcs + paysages + rencontres
# (branche ici tes paysages / PNJs / ennemis)
# ==========================================================
ARC_1 = "ARC_OMBRES"   # Attenin
ARC_2 = "ARC_LUXUS"
ARC_3 = "ARC_DODO"
ARC_4 = "ARC_SHAKIR"

def arc_for_player(player: Dict[str, Any]) -> str:
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

# Paysages: remplace les strings par tes IDs réels
LANDSCAPES_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["docks_brumeux", "neon_alley", "ruelle_sale", "parking_sombre"],
    ARC_2: ["quartier_luxe", "casino_floor", "hotel_rooftop", "galerie_art"],
    ARC_3: ["atelier", "backroom", "entrepot", "rue_industrielle"],
    ARC_4: ["club_backstage", "arena", "studio_clip", "toit_sous_neons"],
}

# Ennemis/rencontres
ENCOUNTERS_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["voyou", "chien_errant", "rat_mutant", "coyote"],
    ARC_2: ["garde_prive", "arnaqueur", "chasseur_de_primes", "drone_surveillance"],
    ARC_3: ["rival", "saboteur", "flic_corrompu", "membre_gang"],
    ARC_4: ["fanatique", "bodyguard", "sniper", "meute_urbaine"],
}

# PNJ (optionnel)
NPCS_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["Vieux SDF", "Dockman muet", "Graffeur"],
    ARC_2: ["Hôtesse VIP", "Collectionneur", "Croupier louche"],
    ARC_3: ["Ouvrier", "Dealer repenti", "Manager nerveux"],
    ARC_4: ["Roadie", "Danseuse", "Coach"],
}

MICROBOSSES_BY_ARC: Dict[str, List[str]] = {
    ARC_1: ["Veilleur des Docks", "Mère des Chiens", "Rôdeur au Néon"],
    ARC_2: ["Le Notaire Blanc", "La Veuve Dorée", "Le Concierge"],
    ARC_3: ["Le Saboteur", "La Main Noire"],
    ARC_4: ["Le Tourneur", "Le Hurleur"],
}

BOSS_BY_ARC: Dict[str, str] = {
    ARC_1: "ATTENIN",
    ARC_2: "LUXUS",
    ARC_3: "DODO",
    ARC_4: "SHAKIR",
}

def _rng_seed(discord_id: int, date_key: str, extra: str = "") -> random.Random:
    return random.Random(f"{date_key}:{discord_id}:{extra}")

# ==========================================================
# Daily state machine (robuste)
# ==========================================================
def load_daily_state(player: Dict[str, Any]) -> Dict[str, Any]:
    return _safe_load_json(str(player.get("state_json", "") or ""))

def is_active_daily(state: Dict[str, Any], date_key: str) -> bool:
    return bool(state and state.get("mode") == "daily" and state.get("date_key") == date_key)

def begin_or_resume_daily(
    s: SheetsService,
    *,
    discord_id: int,
) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    """
    Retourne (player_row_i, player, state)
    - si state_json daily existe pour today => reprend
    - sinon => crée un nouveau state_json daily
    """
    row_i, player = get_player_row(s, discord_id)
    if not row_i or not player:
        raise RuntimeError("Player introuvable dans HUNT_PLAYERS.")

    dk = today_key()
    state = load_daily_state(player)

    # reprise
    if is_active_daily(state, dk):
        if not state.get("pending"):
            state = _generate_pending(state, discord_id)
            update_state(s, row_i, state)
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

    arc = arc_for_player(player)

    state = {
        "mode": "daily",
        "date_key": dk,
        "run_id": str(uuid.uuid4()),
        "step": 1,
        "max_steps": 3,
        "arc": arc,
        "hp": max(1, min(hp, hp_max)),
        "hp_max": hp_max,
        "log": [],
        "flags": {
            "microboss_kills": 0,
            "boss_killed": False,
        },
        "pending": None,
    }

    state = _generate_pending(state, discord_id)
    update_state(s, row_i, state)
    return row_i, player, state

def _generate_pending(state: Dict[str, Any], discord_id: int) -> Dict[str, Any]:
    dk = str(state.get("date_key"))
    arc = str(state.get("arc") or ARC_1)
    step = int(state.get("step", 1) or 1)

    rnd = _rng_seed(discord_id, dk, extra=f"pending:{step}")

    # difficulté par step
    diff = "EASY" if step == 1 else ("MED" if step == 2 else "HARD")

    # microboss (chance)
    micro_chance = 0.08
    is_micro = (rnd.random() < micro_chance)

    scene = rnd.choice(LANDSCAPES_BY_ARC.get(arc, ["rue"]))
    npc = rnd.choice(NPCS_BY_ARC.get(arc, ["Inconnu"])) if rnd.random() < 0.35 else ""

    if is_micro:
        encounter = rnd.choice(MICROBOSSES_BY_ARC.get(arc, ["Microboss"]))
        kind = "MICROBOSS"
        diff = "HARD"
    else:
        encounter = rnd.choice(ENCOUNTERS_BY_ARC.get(arc, ["voyou"]))
        kind = "ENEMY"

    state["pending"] = {
        "scene": scene,
        "encounter": encounter,
        "npc": npc,
        "kind": kind,
        "difficulty": diff,
    }
    return state

def _roll_2d20(discord_id: int, date_key: str, step: int, choice: str) -> Tuple[int, int]:
    rnd = random.Random(f"{date_key}:{discord_id}:{step}:{choice}")
    return rnd.randint(1, 20), rnd.randint(1, 20)

def _target_for_difficulty(diff: str) -> int:
    d = (diff or "MED").upper()
    if d == "EASY":
        return 20
    if d == "HARD":
        return 26
    return 23

def apply_daily_choice(
    s: SheetsService,
    *,
    player_row_i: int,
    player: Dict[str, Any],
    state: Dict[str, Any],
    discord_id: int,
    choice: str,  # explore|negotiate|fight|steal
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Retourne (new_state_or_None_if_finished, outcome)
    outcome contient de quoi afficher un message + résumer.
    """
    pending = state.get("pending") or {}
    dk = str(state.get("date_key"))
    step = int(state.get("step", 1) or 1)
    diff = str(pending.get("difficulty") or "MED").upper()
    target = _target_for_difficulty(diff)

    d1, d2 = _roll_2d20(discord_id, dk, step, choice)
    score = d1 + d2
    win = score >= target

    # base rewards (scalées par step)
    base_money = 18 + step * 6
    base_xp = 10 + step * 5

    money_delta = base_money if win else max(5, base_money // 3)
    xp_delta = base_xp if win else max(2, base_xp // 3)

    # HP (pénalité si lose)
    hp = int(state.get("hp", 100) or 100)
    hp_max = int(state.get("hp_max", 100) or 100)
    hp_delta = 0
    jail_hours = 0

    if not win:
        hp_delta = -random.randint(6, 14)
        if choice == "steal" and d1 <= 5:
            jail_hours = random.randint(2, 12)

    # microboss bonus si win
    if str(pending.get("kind")) == "MICROBOSS" and win:
        money_delta += 20
        xp_delta += 15
        state.setdefault("flags", {})
        state["flags"]["microboss_kills"] = int(state["flags"].get("microboss_kills", 0) or 0) + 1

    hp2 = max(1, min(hp_max, hp + hp_delta))
    state["hp"] = hp2

    # log
    state.setdefault("log", []).append({
        "step": step,
        "scene": pending.get("scene", ""),
        "encounter": pending.get("encounter", ""),
        "npc": pending.get("npc", ""),
        "kind": pending.get("kind", ""),
        "difficulty": diff,
        "choice": choice,
        "d20": [d1, d2],
        "score": score,
        "target": target,
        "result": "WIN" if win else "LOSE",
        "hp_delta": hp_delta,
        "money_delta": money_delta,
        "xp_delta": xp_delta,
        "jail_hours": jail_hours,
    })

    # step++
    step2 = step + 1
    state["step"] = step2

    finished = step2 > int(state.get("max_steps", 3) or 3)

    if not finished:
        # next pending
        state["pending"] = None
        state = _generate_pending(state, discord_id)
        update_state(s, player_row_i, state)

        return state, {
            "finished": False,
            "mark": "✅" if win else "❌",
            "win": win,
            "score": score,
            "target": target,
            "hp": hp2,
            "hp_delta": hp_delta,
            "money_delta": money_delta,
            "xp_delta": xp_delta,
            "jail_hours": jail_hours,
            "next_pending": state.get("pending") or {},
            "step": step,
            "step_next": step2,
            "max_steps": int(state.get("max_steps", 3) or 3),
        }

    # FINISH => créditer le player + clear state_json
    outcome = finalize_daily(
        s,
        player_row_i=player_row_i,
        player=player,
        discord_id=discord_id,
        state=state
    )
    return None, outcome

def finalize_daily(
    s: SheetsService,
    *,
    player_row_i: int,
    player: Dict[str, Any],
    discord_id: int,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    dk = str(state.get("date_key"))
    logs = state.get("log") or []

    def _i(v, d=0):
        try:
            return int(v or 0)
        except Exception:
            return d

    money_total = sum(_i(x.get("money_delta", 0)) for x in logs)
    xp_total = sum(_i(x.get("xp_delta", 0)) for x in logs)
    jail_hours = max([_i(x.get("jail_hours", 0)) for x in logs] + [0])

    cur_money = _i(player.get("hunt_dollars", 0))
    cur_xp = _i(player.get("xp", 0))
    cur_xpt = _i(player.get("xp_total", 0))
    cur_runs = _i(player.get("total_runs", 0))
    hp_end = _i(state.get("hp", player.get("hp", 100)))

    # update player
    s.update_cell_by_header(T_PLAYERS, player_row_i, "hunt_dollars", cur_money + money_total)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "xp", cur_xp + xp_total)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "xp_total", cur_xpt + xp_total)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "hp", hp_end)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "last_daily_date", dk)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "total_runs", cur_runs + 1)
    s.update_cell_by_header(T_PLAYERS, player_row_i, "updated_at", now_iso())

    if jail_hours > 0:
        apply_jail(s, player_row_i, jail_hours)

    # append daily log (si l'onglet existe chez toi)
    try:
        s.append_by_headers(T_DAILIES, {
            "date_key": dk,
            "discord_id": str(discord_id),
            "run_id": str(state.get("run_id")),
            "arc": str(state.get("arc")),
            "result": "DONE",
            "money_delta": int(money_total),
            "xp_delta": int(xp_total),
            "jail_delta_hours": int(jail_hours),
            "story": " | ".join([f"{x.get('choice')}:{x.get('encounter')}:{x.get('result')}" for x in logs])[:4500],
            "rewards_json": json.dumps({"steps": logs}, ensure_ascii=False),
            "created_at": now_iso(),
        })
    except Exception:
        # si pas d'onglet HUNT_DAILIES, on n'empêche pas la fin
        pass

    # clear state_json
    clear_state(s, player_row_i)

    return {
        "finished": True,
        "date_key": dk,
        "arc": str(state.get("arc")),
        "boss_hint": BOSS_BY_ARC.get(str(state.get("arc")), ""),
        "hp_end": hp_end,
        "money_total": money_total,
        "xp_total": xp_total,
        "jail_hours": jail_hours,
        "steps": logs,
    }
