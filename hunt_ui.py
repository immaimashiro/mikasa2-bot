# hunt_ui.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import discord
from discord import ui

import hunt_services
from services import now_iso, now_fr, PARIS_TZ, display_name, catify
import hunt_domain

# ==========================================================
# Mini "moteur" de rencontre
# - Simple mais extensible
# - Sauvegarde après CHAQUE action
# ==========================================================
ENEMIES = [
    {"id": "rat", "name": "Rat mutant", "hp": 10, "atk": (1, 4), "gold": (8, 18)},
    {"id": "coyote", "name": "Coyote famélique", "hp": 14, "atk": (2, 6), "gold": (10, 25)},
    {"id": "gang", "name": "Voyou de ruelle", "hp": 16, "atk": (2, 7), "gold": (12, 30)},
    {"id": "hound", "name": "Chien errant nerveux", "hp": 12, "atk": (2, 5), "gold": (10, 22)},
]

ALLY_TAGS = ["MAI", "ROXY", "LYA", "JACKO", "DRACO"]


def _roll(a: int, b: int) -> int:
    return random.randint(a, b)

def _d20() -> int:
    return hunt_services.roll_d20()

def _clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))

def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _now_fr_str() -> str:
    return now_fr().astimezone(PARIS_TZ).strftime("%d/%m %H:%M")


# Tu remplaceras les URLs par tes liens S3 quand tu les upload
AVATARS = [
    ("MAI",   "Mai",   "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Mai.png"),
    ("ROXY",  "Roxy",  "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Roxy.png"),
    ("LYA",   "Lya",   "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Lya.png"),
    ("ZACKO", "Zacko", "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Zacko.png"),
    ("DRACO", "Draco", "https://github.com/immaimashiro/mikasa2-bot/blob/6cc14e1332d0ffdc2a305ba9d4cab67de3ea2140/Draco.png"),
]


class HuntAvatarView(ui.View):
    def __init__(self, *, services, discord_id: int, code_vip: str, pseudo: str, is_employee: bool):
        super().__init__(timeout=None)  # ✅ pas de timeout
        self.s = services
        self.discord_id = discord_id
        self.code_vip = code_vip
        self.pseudo = pseudo
        self.is_employee = bool(is_employee)

        self.add_item(HuntAvatarSelect(self))
        self.add_item(HuntAvatarCloseButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre /hunt avatar."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        e = discord.Embed(
            title="🎭 Choix du personnage",
            description=(
                f"👤 **{self.pseudo}** • `{self.code_vip}`\n\n"
                "Choisis ton personnage de la direction SubUrban.\n"
                "Ton nom s’affichera ensuite comme :\n"
                f"**{self.pseudo} [MAI]** (exemple)\n\n"
                "✅ Aucun chrono ici, prends ton temps."
            ),
            color=discord.Color.dark_purple()
        )
        e.set_footer(text="Mikasa sort les fiches perso. 🐾")
        return e


class HuntAvatarSelect(ui.Select):
    def __init__(self, view: HuntAvatarView):
        options = []
        for tag, label, _url in AVATARS:
            options.append(discord.SelectOption(label=label, value=tag, description=f"Choisir {label}"))

        super().__init__(
            placeholder="Choisir un personnage…",
            options=options,
            min_values=1,
            max_values=1
        )
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        tag = self.values[0]
        url = next((u for (t, _lab, u) in AVATARS if t == tag), "")

        hunt_services.set_avatar(self.v.s, discord_id=self.v.discord_id, avatar_tag=tag, avatar_url=url)

        # ✅ PUBLIC: annonce dans le salon
        try:
            public = discord.Embed(
                    title="🎭 Nouveau personnage Hunt",
                description=f"**{interaction.user.display_name}** a choisi **[{tag}]** !",
                color=discord.Color.gold()
            )
            if url:
                public.set_thumbnail(url=url)
            public.set_footer(text="Mikasa griffonne le choix dans le registre. 🐾")
            await interaction.channel.send(embed=public)
        except Exception:
            pass

        # privé: confirmation + thumbnail
        e = discord.Embed(
            title="✅ Avatar choisi",
            description=f"Tu joueras désormais en **[{tag}]**.\nNom affiché: **{self.v.pseudo} [{tag}]**",
            color=discord.Color.green()
        )
        if url:
            e.set_thumbnail(url=url)
        e.set_footer(text="Mikasa note ça proprement. 🐾")

        await interaction.response.edit_message(embed=e, view=self.v)



class HuntAvatarCloseButton(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Panneau fermé.", embed=None, view=self.view)


# ==========================================================
# State sérialisé en JSON dans HUNT_DAILY.notes
# ==========================================================
def make_initial_state(
    *,
    code_vip: str,
    pseudo: str,
    employee_boost: bool,
    forced_enemy_id: Optional[str] = None
) -> Dict[str, Any]:
    enemy = None
    if forced_enemy_id:
        enemy = next((e for e in ENEMIES if e["id"] == forced_enemy_id), None)
    if not enemy:
        enemy = random.choice(ENEMIES)

    state = {
        "v": 1,
        "phase": "INTRO",  # INTRO -> COMBAT -> RESOLVE -> DONE
        "code_vip": code_vip,
        "pseudo": pseudo,

        "turn": 1,
        "log": [],

        "player": {
            "hp": 20,
            "max_hp": 20,
            "shield": 0,       # petit bouclier temporaire
            "potions": 1,      # bandage/potion simple
            "money_gain": 0,   # gain accumulé sur la run
        },

        "ally": {
            "active": False,
            "tag": "",
            "hp": 0,
            "max_hp": 0,
            "used_this_week": False,
        },

        "enemy": {
            "id": enemy["id"],
            "name": enemy["name"],
            "hp": int(enemy["hp"]),
            "max_hp": int(enemy["hp"]),
        },

        "flags": {
            "employee_boost": bool(employee_boost),
            "can_spawn_ally": True,
        }
    }
    return state


def state_add_log(state: Dict[str, Any], line: str) -> None:
    state.setdefault("log", [])
    state["log"].append(line)
    # limite la taille pour Sheets
    if len(state["log"]) > 30:
        state["log"] = state["log"][-30:]


def dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False)

def load_state(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = raw.strip()
    # si quelqu’un a mis autre chose qu’un JSON, on ignore
    if not (raw.startswith("{") and raw.endswith("}")):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ==========================================================
# Sauvegarde dans HUNT_DAILY
# ==========================================================
def save_state_to_daily(
    s,
    *,
    discord_id: int,
    state: Dict[str, Any],
    result: str = "",
) -> None:
    """
    On met le JSON dans HUNT_DAILY.notes, et optionnellement HUNT_DAILY.result
    """
    dk = hunt_services.today_key_fr()
    did = str(discord_id)

    rows = s.get_all_records(hunt_services.T_DAILY)
    found = None
    for idx, r in enumerate(rows, start=2):
        if str(r.get("day_key", "")).strip() == dk and str(r.get("discord_id", "")).strip() == did:
            found = (idx, r)
            break
    if not found:
        return

    row_i, _ = found
    try:
        s.update_cell_by_header(hunt_services.T_DAILY, row_i, "notes", dump_state(state))
    except Exception:
        pass
    if result:
        try:
            s.update_cell_by_header(hunt_services.T_DAILY, row_i, "result", result[:200])
        except Exception:
            pass


# ==========================================================
# UI
# ==========================================================
class HuntDailyView(ui.View):
    """
    - Pas de chrono de décision
    - Sauvegarde après chaque action
    - Tour par tour
    """
    def __init__(
        self,
        *,
        services,
        author_id: int,
        state: Dict[str, Any],
    ):
        super().__init__(timeout=30 * 60)  # limite technique Discord (pas un chrono de choix)
        self.s = services
        self.author_id = author_id
        self.state = state

        self.btn_attack = HuntAttackButton()
        self.btn_defend = HuntDefendButton()
        self.btn_potion = HuntPotionButton()
        self.btn_flee = HuntFleeButton()
        self.btn_continue = HuntContinueButton()
        self.btn_steal = HuntStealButton()
        self.btn_finish = HuntFinishNpcButton()
        
        self.add_item(self.btn_steal)
        self.add_item(self.btn_finish)
        self.add_item(self.btn_attack)
        self.add_item(self.btn_defend)
        self.add_item(self.btn_potion)
        self.add_item(self.btn_flee)
        self.add_item(self.btn_continue)

        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("😾 Pas touche. Lance ton propre `/hunt daily`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

    def _sync_buttons(self) -> None:
        phase = self.state.get("phase", "INTRO")
        done = (phase == "DONE")

        # Le bouton continue sert à passer INTRO -> COMBAT ou RESOLVE -> DONE
        self.btn_continue.disabled = done

        if phase in ("INTRO",):
            self.btn_attack.disabled = True
            self.btn_defend.disabled = True
            self.btn_potion.disabled = True
            self.btn_flee.disabled = True

        elif phase in ("COMBAT",):
            self.btn_attack.disabled = False
            self.btn_defend.disabled = False
            self.btn_potion.disabled = False
            self.btn_flee.disabled = False

        elif phase in ("RESOLVE",):
            self.btn_attack.disabled = True
            self.btn_defend.disabled = True
            self.btn_potion.disabled = True
            self.btn_flee.disabled = True

        elif done:
            self.btn_attack.disabled = True
            self.btn_defend.disabled = True
            self.btn_potion.disabled = True
            self.btn_flee.disabled = True

        elif phase == "COMBAT":
            self.btn_steal.disabled = False
            self.btn_finish.disabled = False
        else:
            self.btn_steal.disabled = True
            self.btn_finish.disabled = True


    def build_embed(self) -> discord.Embed:
        pseudo = self.state.get("pseudo", "Quelqu’un")
        code = self.state.get("code_vip", "SUB-????-????")

        p = self.state["player"]
        e = self.state["enemy"]
        ally = self.state.get("ally", {})

        phase = self.state.get("phase", "INTRO")
        turn = int(self.state.get("turn", 1))

        title = "🧭 HUNT • Daily RPG"
        if phase == "INTRO":
            title = "🧭 HUNT • Rencontre"
        elif phase == "COMBAT":
            title = "⚔️ HUNT • Combat"
        elif phase == "RESOLVE":
            title = "🎁 HUNT • Résultat"
        elif phase == "DONE":
            title = "✅ HUNT • Terminé"

        desc = (
            f"👤 **{display_name(pseudo)}** (`{code}`)\n"
            f"🕰️ {_now_fr_str()} (FR)\n"
        )

        emb = discord.Embed(title=title, description=desc, color=discord.Color.dark_purple())

        # Barres HP simples
        emb.add_field(
            name="🧍 Joueur",
            value=(
                f"❤️ **{p['hp']} / {p['max_hp']}**\n"
                f"🛡️ Bouclier: **{p.get('shield', 0)}**\n"
                f"🩹 Bandages: **{p.get('potions', 0)}**\n"
                f"💵 Gain run: **${p.get('money_gain', 0)}**"
            ),
            inline=True
        )

        ally_line = "—"
        if ally and ally.get("active"):
            ally_line = f"🤝 **[{ally.get('tag','?')}]** ❤️ {ally.get('hp',0)}/{ally.get('max_hp',0)}"

        emb.add_field(
            name="🧑‍🤝‍🧑 Allié",
            value=ally_line,
            inline=True
        )

        emb.add_field(
            name=f"👹 Ennemi (Tour {turn})",
            value=f"**{e['name']}**\n❤️ **{e['hp']} / {e['max_hp']}**",
            inline=False
        )

        # Log narratif
        logs = self.state.get("log", [])
        if not logs:
            logs = ["Mikasa entrouvre un vieux carnet… quelque chose bouge dans l’ombre."]
        emb.add_field(name="📜 Récit", value="\n".join(logs[-10:]), inline=False)

        emb.set_footer(text="Pas de chrono: prends ton temps. Les boutons expirent seulement si Discord coupe la view.")
        return emb

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ---------------------------
    # Mécaniques
    # ---------------------------
    def maybe_spawn_ally(self) -> None:
        """
        50% pour employés de rencontrer un membre de la direction pour aider (1 max / semaine),
        sinon plus rare pour les autres.
        Note: On ne met pas ici le 'pas le même que l’avatar' pour l’instant, ça viendra
        quand on ajoutera la sélection de personnage.
        """
        if self.state["ally"]["active"]:
            return
        if not self.state["flags"].get("can_spawn_ally", True):
            return

        employee = bool(self.state["flags"].get("employee_boost"))
        chance = 50 if employee else 18
        if _roll(1, 100) > chance:
            return

        tag = random.choice(ALLY_TAGS)
        self.state["ally"] = {
            "active": True,
            "tag": tag,
            "hp": 12,
            "max_hp": 12,
            "used_this_week": True,
        }
        self.state["flags"]["can_spawn_ally"] = False
        state_add_log(self.state, f"✨ Mikasa hérisse ses poils… un allié surgit: **[{tag}]**!")

    def enemy_attack(self) -> int:
        enemy_id = self.state["enemy"]["id"]
        base = next((x for x in ENEMIES if x["id"] == enemy_id), None)
        if not base:
            dmg = _roll(1, 4)
        else:
            dmg = _roll(base["atk"][0], base["atk"][1])

        # bouclier absorbe d’abord
        shield = int(self.state["player"].get("shield", 0))
        if shield > 0:
            absorbed = min(shield, dmg)
            shield -= absorbed
            dmg -= absorbed
            self.state["player"]["shield"] = shield
            if absorbed > 0:
                state_add_log(self.state, f"🛡️ Ton bouclier absorbe **{absorbed}** dégâts.")

        # si allié actif, 25% chance qu’il prenne le coup à ta place
        ally = self.state.get("ally", {})
        if ally and ally.get("active") and _roll(1, 100) <= 25:
            ally["hp"] = max(0, int(ally["hp"]) - max(1, dmg))
            state_add_log(self.state, f"🤝 **[{ally.get('tag','?')}]** encaisse le coup: **-{dmg} HP**.")
            if ally["hp"] <= 0:
                ally["active"] = False
                state_add_log(self.state, f"💥 L’allié disparaît dans la fumée… (KO)")
            self.state["ally"] = ally
            return 0

        # sinon sur joueur
        self.state["player"]["hp"] = max(0, int(self.state["player"]["hp"]) - max(1, dmg))
        return dmg

    def check_end(self) -> Optional[str]:
        """
        Retourne "WIN" / "LOSE" / None
        """
        if int(self.state["enemy"]["hp"]) <= 0:
            return "WIN"
        if int(self.state["player"]["hp"]) <= 0:
            return "LOSE"
        return None

    def apply_win_rewards(self) -> None:
        enemy_id = self.state["enemy"]["id"]
        base = next((x for x in ENEMIES if x["id"] == enemy_id), None)
        gold = _roll(10, 25) if not base else _roll(base["gold"][0], base["gold"][1])

        # petit bonus d20 “héroïque”
        d = _d20()
        bonus = max(0, d - 12) * _roll(1, 3)

        gain = gold + bonus
        self.state["player"]["money_gain"] = int(self.state["player"].get("money_gain", 0)) + gain
        state_add_log(self.state, f"🎁 Butin trouvé: **+${gain}** (jet {d}).")

    def apply_death_penalty(self) -> Dict[str, Any]:
        """
        Mort = perte partielle:
        - perte 25% du gain run
        - chance de perdre 1 bandage
        - prison 10% chance (1 à 4h) “ramassé par les flics”
        """
        p = self.state["player"]
        lost = int(p.get("money_gain", 0)) // 4
        p["money_gain"] = max(0, int(p.get("money_gain", 0)) - lost)

        if int(p.get("potions", 0)) > 0 and _roll(1, 100) <= 35:
            p["potions"] = int(p.get("potions", 0)) - 1
            state_add_log(self.state, "🩹 Dans la panique… tu as perdu **1 bandage**.")

        jail_hours = 0
        if _roll(1, 100) <= 10:
            jail_hours = _roll(1, 4)

        return {"lost_money": lost, "jail_hours": jail_hours}


# ==========================================================
# Buttons
# ==========================================================
class HuntContinueButton(ui.Button):
    def __init__(self):
        super().__init__(label="➡️ Continuer", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        phase = view.state.get("phase", "INTRO")

        if phase == "INTRO":
            # spawn ally possible au début
            view.maybe_spawn_ally()
            state_add_log(view.state, "⚔️ L’ennemi s’approche. Choisis ton action.")
            view.state["phase"] = "COMBAT"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
            return await view.refresh(interaction)

        if phase == "RESOLVE":
            # terminer la daily
            view.state["phase"] = "DONE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="DONE")
            # marque finished_at
            try:
                hunt_services.finish_daily(view.s, discord_id=interaction.user.id, result="DONE", notes=dump_state(view.state))
            except Exception:
                pass
            view._sync_buttons()
            return await view.refresh(interaction)

        # DONE ou COMBAT: rien
        await view.refresh(interaction)


class HuntAttackButton(ui.Button):
    def __init__(self):
        super().__init__(label="🗡️ Attaquer", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore

        # tour joueur
        d = _d20()
        dmg = 0
        if d >= 18:
            dmg = _roll(6, 10)
            state_add_log(view.state, f"💥 Critique! Jet **{d}** → **-{dmg} HP** à l’ennemi.")
        elif d >= 11:
            dmg = _roll(3, 7)
            state_add_log(view.state, f"🗡️ Touché. Jet **{d}** → **-{dmg} HP**.")
        else:
            state_add_log(view.state, f"😬 Raté. Jet **{d}**. L’ennemi esquive.")

        view.state["enemy"]["hp"] = max(0, int(view.state["enemy"]["hp"]) - dmg)

        end = view.check_end()
        if end == "WIN":
            state_add_log(view.state, "🏆 L’ennemi s’écroule.")
            view.apply_win_rewards()
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="WIN")
            return await view.refresh(interaction)

        # riposte ennemi
        edmg = view.enemy_attack()
        if edmg > 0:
            state_add_log(view.state, f"👹 Riposte: **-{edmg} HP**.")

        end = view.check_end()
        if end == "LOSE":
            state_add_log(view.state, "💀 Tu tombes… Mikasa referme les yeux un instant.")
            penalty = view.apply_death_penalty()
            view.state["phase"] = "RESOLVE"
            # applique prison si besoin
            if penalty.get("jail_hours", 0) > 0:
                # jail_until sur player sheet
                p_row = hunt_services.get_player(view.s, interaction.user.id)
                if p_row:
                    row_i, player = p_row
                    until = now_fr() + hunt_services.timedelta(hours=int(penalty["jail_hours"]))  # fallback
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="LOSE")
            return await view.refresh(interaction)

        # next turn
        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)


class HuntDefendButton(ui.Button):
    def __init__(self):
        super().__init__(label="🛡️ Se défendre", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore

        d = _d20()
        shield_gain = 0
        if d >= 16:
            shield_gain = _roll(4, 7)
            state_add_log(view.state, f"🛡️ Garde parfaite. Jet **{d}** → bouclier +{shield_gain}.")
        elif d >= 10:
            shield_gain = _roll(2, 4)
            state_add_log(view.state, f"🛡️ Tu te protèges. Jet **{d}** → bouclier +{shield_gain}.")
        else:
            shield_gain = 1
            state_add_log(view.state, f"🛡️ Garde fragile. Jet **{d}** → bouclier +{shield_gain}.")

        view.state["player"]["shield"] = int(view.state["player"].get("shield", 0)) + shield_gain

        # riposte ennemi
        edmg = view.enemy_attack()
        if edmg > 0:
            state_add_log(view.state, f"👹 L’ennemi frappe: **-{edmg} HP**.")

        end = view.check_end()
        if end == "LOSE":
            state_add_log(view.state, "💀 KO… Mikasa soupire, puis note l’incident.")
            view.apply_death_penalty()
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="LOSE")
            return await view.refresh(interaction)

        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)


class HuntPotionButton(ui.Button):
    def __init__(self):
        super().__init__(label="🩹 Bandage", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        p = view.state["player"]
        pot = int(p.get("potions", 0))

        if pot <= 0:
            await interaction.response.send_message("😾 Tu n’as plus de bandage.", ephemeral=True)
            return

        heal = _roll(6, 12)
        p["potions"] = pot - 1
        p["hp"] = _clamp(int(p["hp"]) + heal, 0, int(p["max_hp"]))
        state_add_log(view.state, f"🩹 Tu te soignes: **+{heal} HP**.")

        # riposte ennemi (petite chance qu’il te laisse respirer)
        if _roll(1, 100) <= 75:
            edmg = view.enemy_attack()
            if edmg > 0:
                state_add_log(view.state, f"👹 Pendant que tu te soignes… **-{edmg} HP**.")

        end = view.check_end()
        if end == "LOSE":
            state_add_log(view.state, "💀 Tu t’effondres malgré tout.")
            view.apply_death_penalty()
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="LOSE")
            return await view.refresh(interaction)

        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)


class HuntFleeButton(ui.Button):
    def __init__(self):
        super().__init__(label="🏃 Fuir", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore

        d = _d20()
        if d >= 12:
            state_add_log(view.state, f"🏃 Tu fuis avec succès. Jet **{d}**.")
            # petite récompense quand même
            view.state["player"]["money_gain"] = int(view.state["player"].get("money_gain", 0)) + _roll(5, 12)
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="FLEE")
            return await view.refresh(interaction)

        # échec: attaque gratuite
        state_add_log(view.state, f"😬 Fuite ratée. Jet **{d}**.")
        edmg = view.enemy_attack()
        if edmg > 0:
            state_add_log(view.state, f"👹 L’ennemi te rattrape: **-{edmg} HP**.")

        end = view.check_end()
        if end == "LOSE":
            state_add_log(view.state, "💀 KO dans la fuite…")
            view.apply_death_penalty()
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="LOSE")
            return await view.refresh(interaction)

        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)

class HuntDailyView(ui.View):
    def __init__(self, *, services, discord_id: int, code_vip: str, player_row_i: int, player: dict, daily_row_i: int, daily_row: dict, tester_bypass: bool):
        super().__init__(timeout=None)
        self.s = services
        self.discord_id = discord_id
        self.code_vip = code_vip
        self.player_row_i = player_row_i
        self.player = player
        self.daily_row_i = daily_row_i
        self.daily_row = daily_row
        self.tester_bypass = tester_bypass

        step = int(daily_row.get("step", 0) or 0)
        raw = str(daily_row.get("state_json", "") or "").strip() or "{}"
        try:
            self.state = json.loads(raw)
        except Exception:
            self.state = {}

        if not self.state:
            self.state = hunt_domain.new_daily_state(player)

        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton /hunt daily."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        avatar_tag = str(self.player.get("avatar_tag","") or "").strip()
        avatar_url = str(self.player.get("avatar_url","") or "").strip()

        hp = int(self.state.get("player_hp", 20))
        hpmax = int(self.state.get("player_hp_max", 20))
        enemy = self.state.get("enemy", {})
        ehp = int(enemy.get("hp", 0))
        ehpmax = int(enemy.get("hp_max", 0))

        e = discord.Embed(
            title="🗺️ Hunt Daily",
            description=(
                f"🎭 **{self.player.get('pseudo','')}** {f'[{avatar_tag}]' if avatar_tag else ''}\n"
                f"❤️ PV: **{hp}/{hpmax}**\n"
                f"👹 Ennemi: **{enemy.get('name','?')}** • PV **{ehp}/{ehpmax}**\n\n"
                f"📜 {self.state.get('scene','')}\n"
            ),
            color=discord.Color.dark_purple()
        )
        if avatar_url:
            e.set_thumbnail(url=avatar_url)

        logs = self.state.get("log", [])[-6:]
        if logs:
            e.add_field(name="🧾 Journal", value="\n".join(logs), inline=False)

        if self.state.get("done"):
            xp = int(self.state.get("reward_xp", 0))
            dol = int(self.state.get("reward_dollars", 0))
            extra = "🚨 **Prison**" if self.state.get("jailed") else ("💀 **KO**" if self.state.get("died") else "🏁 **Victoire**")
            e.add_field(name="✅ Résultat", value=f"{extra}\n+{dol} Hunt$ • +{xp} XP", inline=False)

        e.set_footer(text="Chaque choix sauvegarde. Pas de retour arrière. 🐾")
        return e

    def _sync_buttons(self):
        done = bool(self.state.get("done"))
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = done

    async def _save(self):
        # incrémente step: anti-retour arrière
        step = int(self.daily_row.get("step", 0) or 0) + 1
        self.daily_row["step"] = step
        hunt_services.save_daily_state(self.s, self.daily_row_i, step=step, state=self.state)

    async def _finalize_if_done(self):
        if not self.state.get("done"):
            return

        xp = int(self.state.get("reward_xp", 0))
        dol = int(self.state.get("reward_dollars", 0))
        dmg_taken = max(0, int(self.state.get("player_hp_max", 20)) - int(self.state.get("player_hp", 20)))

        died = bool(self.state.get("died"))
        jailed = bool(self.state.get("jailed"))

        # update player: dollars + xp + stats_hp (on remet au max pour le lendemain, sinon trop punitif)
        try:
            cur_d = int(self.player.get("hunt_dollars", 0) or 0)
        except Exception:
            cur_d = 0

        self.s.update_cell_by_header("HUNT_PLAYERS", self.player_row_i, "hunt_dollars", cur_d + dol)

        # XP (simple pour l’instant)
        try:
            cur_xp = int(self.player.get("xp", 0) or 0)
            cur_total = int(self.player.get("xp_total", 0) or 0)
        except Exception:
            cur_xp, cur_total = 0, 0
        self.s.update_cell_by_header("HUNT_PLAYERS", self.player_row_i, "xp", cur_xp + xp)
        self.s.update_cell_by_header("HUNT_PLAYERS", self.player_row_i, "xp_total", cur_total + xp)

        # prison
        if jailed:
            hours = int(self.state.get("jail_hours", 6) or 6)
            until = (now_fr()).astimezone(PARIS_TZ)
            until = until.replace(microsecond=0) + __import__("datetime").timedelta(hours=hours)
            self.s.update_cell_by_header("HUNT_PLAYERS", self.player_row_i, "jail_until", until.isoformat())

        # last daily
        self.s.update_cell_by_header("HUNT_PLAYERS", self.player_row_i, "last_daily_date", hunt_services._today_key())

        summary = " | ".join(self.state.get("log", [])[-4:])
        hunt_services.finish_daily(self.s, self.daily_row_i, summary=summary, xp=xp, dollars=dol, dmg=dmg_taken, died=died, jailed=jailed)

    @ui.button(label="🗡️ Attaquer", style=discord.ButtonStyle.danger)
    async def btn_attack(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hunt_domain.apply_attack(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="🩹 Se soigner", style=discord.ButtonStyle.primary)
    async def btn_heal(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hunt_domain.apply_heal(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="👜 Voler", style=discord.ButtonStyle.secondary)
    async def btn_steal(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hunt_domain.apply_steal(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Hunt daily fermé.", embed=None, view=self)

class HuntStealButton(ui.Button):
    def __init__(self):
        super().__init__(label="🧤 Voler", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore

        d = _d20()
        # succès si >= 12
        if d >= 12:
            gain = _roll(12, 35)
            view.state["player"]["money_gain"] = int(view.state["player"].get("money_gain", 0)) + gain
            state_add_log(view.state, f"🧤 Vol réussi (jet {d}) → **+${gain}**.")
            # petite montée de heat quand même
            heat = hunt_services.add_heat(view.s, interaction.user.id, amount=3)
        else:
            state_add_log(view.state, f"🚨 Vol raté (jet {d})… sirènes au loin.")
            # prison pour vol raté
            got = hunt_services.ensure_player(view.s, interaction.user.id)
            _, row = got
            heat = _safe_int(row.get("heat", 0), 0)
            hours = hunt_services.compute_sentence_hours("STEAL", heat=heat, roll=d)
            until = hunt_services.set_jail(view.s, interaction.user.id, hours=hours, reason="Vol raté pendant /hunt daily")
            # heat augmente plus
            hunt_services.add_heat(view.s, interaction.user.id, amount=8)
            view.state["phase"] = "RESOLVE"
            state_add_log(view.state, f"⛓️ Arrêté. Prison jusqu’à **{until.astimezone(PARIS_TZ).strftime('%d/%m %H:%M')}**.")
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="JAIL(STEAL)")
            return await view.refresh(interaction)

        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)


class HuntFinishNpcButton(ui.Button):
    def __init__(self):
        super().__init__(label="☠️ Achever (PNJ)", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore

        d = _d20()
        state_add_log(view.state, f"☠️ Tentative d’achever un PNJ… jet **{d}**.")

        # Réussite narrative si d>=10: tu “tues”
        if d >= 10:
            state_add_log(view.state, "🩸 Le geste est irréversible.")
            # prison pour meurtre très probable
            got = hunt_services.ensure_player(view.s, interaction.user.id)
            _, row = got
            heat = _safe_int(row.get("heat", 0), 0)
            hours = hunt_services.compute_sentence_hours("KILL", heat=heat, roll=d)
            until = hunt_services.set_jail(view.s, interaction.user.id, hours=hours, reason="Meurtre PNJ pendant /hunt daily")
            hunt_services.add_heat(view.s, interaction.user.id, amount=18)

            # petit butin “sale”
            gain = _roll(20, 60)
            view.state["player"]["money_gain"] = int(view.state["player"].get("money_gain", 0)) + gain
            state_add_log(view.state, f"💵 Tu récupères **${gain}**… mais la ville a vu. Prison jusqu’à **{until.astimezone(PARIS_TZ).strftime('%d/%m %H:%M')}**.")
            view.state["phase"] = "RESOLVE"
            save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="JAIL(KILL)")
            return await view.refresh(interaction)

        # échec: tu n’arrives pas à le faire (ton 50/50 “je ne peux pas l’achever”)
        state_add_log(view.state, "😶 Finalement… tu n’y arrives pas. Mikasa te regarde sans juger.")
        hunt_services.add_heat(view.s, interaction.user.id, amount=5)

        view.state["turn"] = int(view.state.get("turn", 1)) + 1
        save_state_to_daily(view.s, discord_id=interaction.user.id, state=view.state, result="RUNNING")
        await view.refresh(interaction)

# ==========================================================
# Fonction utilitaire appelée par bot.py
# - Crée la view + embed
# - Le bot.py envoie: followup.send(embed=..., view=..., ephemeral=True)
# ==========================================================
def build_daily_view(
    *,
    services,
    author_id: int,
    code_vip: str,
    pseudo: str,
    employee_boost: bool,
    existing_state_json: str = "",
) -> Tuple[discord.Embed, discord.ui.View, Dict[str, Any]]:
    """
    Si existing_state_json est un JSON valide, on reprend.
    Sinon, on crée un nouvel état.
    """
    st = load_state(existing_state_json) if existing_state_json else None
    if not st:
        st = make_initial_state(
            code_vip=code_vip,
            pseudo=pseudo,
            employee_boost=employee_boost,
        )
        state_add_log(st, f"🌫️ Mikasa te fixe… « {display_name(pseudo)}… j’ai une mission pour toi. »")
        state_add_log(st, "➡️ Appuie sur **Continuer** pour entrer dans la rencontre.")

    view = HuntDailyView(services=services, author_id=author_id, state=st)
    emb = view.build_embed()
    return emb, view, st

