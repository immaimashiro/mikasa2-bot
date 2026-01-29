# hunt_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any
import discord
from discord import ui

import hunt_rpg as rpg
from services import catify, now_fr


# ==========================================================
# Helpers (safe)
# ==========================================================
def _mk_embed(title: str, desc: str, *, color: discord.Color) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v or 0)
    except Exception:
        return default

def _choice_label(choice: str) -> str:
    mapping = {
        "explore": "🧭 Explorer",
        "negotiate": "💬 Négocier",
        "fight": "⚔️ Attaquer",
        "steal": "🧤 Voler",
    }
    return mapping.get(choice, str(choice))

def _diff_badge(d: str) -> str:
    d = (d or "MED").upper()
    if d == "EASY":
        return "🟢 EASY"
    if d == "HARD":
        return "🔴 HARD"
    return "🟠 MED"

def _kind_badge(k: str) -> str:
    k = (k or "").upper()
    if k == "MICROBOSS":
        return "👑 Micro-boss"
    return "👁️ Rencontre"

def _arc_label(arc: str) -> str:
    arc = (arc or "").upper()
    if arc == getattr(rpg, "ARC_1", "ARC_OMBRES"):
        return "ARC I — Ombres"
    if arc == getattr(rpg, "ARC_2", "ARC_LUXUS"):
        return "ARC II — Luxus"
    if arc == getattr(rpg, "ARC_3", "ARC_DODO"):
        return "ARC III — Dodo"
    if arc == getattr(rpg, "ARC_4", "ARC_SHAKIR"):
        return "ARC FINAL — Shakir"
    return arc or "ARC ?"

def _img_for(encounter: str = "", boss_hint: str = "") -> str:
    """
    Récup image depuis rpg.ENCOUNTER_IMAGES si présent.
    Tu peux aussi mapper tes paysages ici plus tard.
    """
    m = getattr(rpg, "ENCOUNTER_IMAGES", {}) or {}
    if not isinstance(m, dict):
        return ""
    e = (encounter or "").strip()
    b = (boss_hint or "").strip()
    return (m.get(e) or m.get(e.lower()) or m.get(e.title()) or m.get(b) or "")


# ==========================================================
# HUB (safe)
# ==========================================================
class HuntHubView(ui.View):
    def __init__(self, *, sheets, discord_id: int, code_vip: str, pseudo: str, is_employee: bool):
        super().__init__(timeout=10 * 60)
        self.s = sheets
        self.discord_id = int(discord_id)
        self.code_vip = str(code_vip)
        self.pseudo = str(pseudo)
        self.is_employee = bool(is_employee)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre HUNT."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        desc = (
            f"👤 <@{self.discord_id}> • 🎴 `{self.code_vip}`\n"
            f"🪪 Pseudo: **{self.pseudo}**\n\n"
            "Choisis une action :\n"
            "• 🗺️ Daily RPG (multi-encounters)\n"
            "• 🎒 Inventaire (placeholder)\n"
            "• 🛒 Shop (placeholder)\n"
        )
        e = _mk_embed("🧭 HUNT • Hub", desc, color=discord.Color.dark_purple())
        e.set_footer(text="Mikasa ouvre ton dossier… 🐾")
        return e

    @ui.button(label="🗺️ Daily RPG", style=discord.ButtonStyle.primary)
    async def btn_daily(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntDailyView(sheets=self.s, discord_id=self.discord_id, code_vip=self.code_vip, pseudo=self.pseudo)
        await view.load()
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @ui.button(label="🎒 Inventaire", style=discord.ButtonStyle.secondary)
    async def btn_inv(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(catify("🐾 Inventaire pas encore branché. On le reconnecte après le RPG."), ephemeral=True)

    @ui.button(label="🛒 Shop", style=discord.ButtonStyle.secondary)
    async def btn_shop(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(catify("🐾 Shop pas encore branché. On le reconnecte après le RPG."), ephemeral=True)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="✅ Hub fermé.", embed=None, view=self)


# ==========================================================
# AVATAR
# ==========================================================
AVATARS: List[Tuple[str, str]] = [
    ("MAI", "https://imgur.com/a2uXTCr"),
    ("ROXY", "https://imgur.com/IP53zgQ"),
    ("LYA", "https://imgur.com/BoCNT1O"),
    ("DRACO", "https://imgur.com/UgsBzKU"),
    ("ZACKO", "https://imgur.com/zHGjjb1"),
]

class HuntAvatarSelect(ui.Select):
    def __init__(self, view: "HuntAvatarView"):
        opts = [discord.SelectOption(label=tag, value=tag) for tag, _ in AVATARS]
        super().__init__(placeholder="Choisis ton personnage…", options=opts, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_tag = self.values[0]
        await interaction.response.edit_message(embed=self.v.build_embed(), view=self.v)

class HuntAvatarConfirm(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Valider", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        v: HuntAvatarView = self.view  # type: ignore
        if not v.selected_tag:
            return await interaction.response.send_message(catify("😾 Choisis un perso d’abord."), ephemeral=True)

        row_i, player = rpg.get_player_row(v.s, v.discord_id)
        if not row_i or not player:
            return await interaction.response.send_message("❌ Player introuvable dans HUNT_PLAYERS.", ephemeral=True)

        url = ""
        for t, u in AVATARS:
            if t == v.selected_tag:
                url = u
                break

        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "avatar_tag", v.selected_tag)
        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "avatar_url", url)
        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "updated_at", now_fr().isoformat(timespec="seconds"))

        for c in v.children:
            c.disabled = True

        e = _mk_embed("✅ Avatar enregistré", f"Ton tag est maintenant **[{v.selected_tag}]**.", color=discord.Color.green())
        if url:
            e.set_thumbnail(url=url)
        e.set_footer(text="Mikasa colle ton badge. 🐾")
        await interaction.response.edit_message(embed=e, view=v)

class HuntAvatarView(ui.View):
    def __init__(self, *, author_id: int, sheets, discord_id: int):
        super().__init__(timeout=5 * 60)
        self.author_id = int(author_id)
        self.discord_id = int(discord_id)
        self.s = sheets
        self.selected_tag: str = ""

        self.add_item(HuntAvatarSelect(self))
        self.add_item(HuntAvatarConfirm())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        desc = "Choisis un perso SubUrban. Ton tag apparaîtra en **[MAI]**, **[ROXY]**, etc."
        if self.selected_tag:
            desc += f"\n\nSélection: **[{self.selected_tag}]**"
        e = _mk_embed("🎭 HUNT • Avatar", desc, color=discord.Color.blurple())
        e.set_footer(text="Astuce: obligatoire avant le Daily (immersion). 🐾")
        return e


# ==========================================================
# DAILY RPG (multi-encounters)
# ==========================================================
CHOICES: List[Tuple[str, str, discord.ButtonStyle]] = [
    ("🧭 Explorer", "explore", discord.ButtonStyle.secondary),
    ("💬 Négocier", "negotiate", discord.ButtonStyle.primary),
    ("⚔️ Attaquer", "fight", discord.ButtonStyle.danger),
    ("🧤 Voler", "steal", discord.ButtonStyle.secondary),
]

class HuntDailyView(ui.View):
    def __init__(self, *, sheets, discord_id: int, code_vip: str, pseudo: str):
        super().__init__(timeout=12 * 60)
        self.s = sheets
        self.discord_id = int(discord_id)
        self.code_vip = str(code_vip)
        self.pseudo = str(pseudo)

        self.player_row_i: Optional[int] = None
        self.player: Optional[Dict[str, Any]] = None
        self.state: Optional[Dict[str, Any]] = None

        for label, val, style in CHOICES:
            self.add_item(HuntDailyChoiceButton(label=label, choice=val, style=style))
        self.add_item(HuntDailyQuestionsButton())
        self.add_item(HuntDailyCloseButton())

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre Daily."), ephemeral=True)
            return False
        return True

    async def load(self) -> None:
        row_i, player, state = rpg.begin_or_resume_daily(self.s, discord_id=self.discord_id)
        self.player_row_i = row_i
        self.player = player
        self.state = state
        self._refresh_questions_button()

    def _require_loaded(self) -> None:
        if self.player_row_i is None or self.player is None or self.state is None:
            raise RuntimeError("DailyView not loaded. Call await view.load() before sending.")

    def _refresh_questions_button(self) -> None:
        # Active Questions uniquement si PNJ présent
        npc = ""
        if self.state:
            npc = str((self.state.get("pending") or {}).get("npc", "") or "").strip()
        for it in self.children:
            if isinstance(it, HuntDailyQuestionsButton):
                it.disabled = (not npc)

    def build_embed(self) -> discord.Embed:
        self._require_loaded()
        st = self.state or {}
        pending = st.get("pending") or {}

        dk = str(st.get("date_key", ""))
        step_cur = _safe_int(st.get("step", 1), 1)
        mx = _safe_int(st.get("max_steps", 3), 3)

        hp = _safe_int(st.get("hp", 100), 100)
        hp_max = _safe_int(st.get("hp_max", 100), 100)

        arc = _arc_label(str(st.get("arc", "")))

        scene = str(pending.get("scene", "rue"))
        encounter = str(pending.get("encounter", "inconnu"))
        npc = str(pending.get("npc", "") or "")
        kind = _kind_badge(str(pending.get("kind", "")))
        diff = _diff_badge(str(pending.get("difficulty", "MED")))

        desc = (
            f"👤 <@{self.discord_id}> • 🎴 `{self.code_vip}`\n"
            f"🪪 **{self.pseudo}**\n"
            f"📚 **{arc}**\n"
            f"🧩 Étape **{step_cur}/{mx}**\n"
            f"❤️ HP: **{hp}/{hp_max}**\n\n"
            f"📍 **Paysage**: `{scene}`\n"
            f"{kind}: **{encounter}** — {diff}\n"
            + (f"🗣️ PNJ: **{npc}**\n" if npc else "")
            + "\nChoisis une action. La progression est sauvegardée."
        )

        e = _mk_embed(f"🗺️ HUNT Daily • {dk}", desc, color=discord.Color.blurple())

        # Image encounter/boss si dispo
        boss_hint = ""
        try:
            boss_hint = str(getattr(rpg, "BOSS_BY_ARC", {}).get(str(st.get("arc")), "") or "")
        except Exception:
            boss_hint = ""
        img = _img_for(encounter=encounter, boss_hint=boss_hint)
        if img:
            e.set_thumbnail(url=img)

        e.set_footer(text="state_json robuste : si tu fermes, tu reprends. 🐾")
        return e

    def build_finished_embed(self, outcome: Dict[str, Any]) -> discord.Embed:
        steps = outcome.get("steps") or []
        dk = str(outcome.get("date_key", ""))
        arc = _arc_label(str(outcome.get("arc", "")))

        money_total = _safe_int(outcome.get("money_total", 0))
        xp_total = _safe_int(outcome.get("xp_total", 0))
        jail_h = _safe_int(outcome.get("jail_hours", 0))
        hp_end = _safe_int(outcome.get("hp_end", 0))
        boss_hint = str(outcome.get("boss_hint", "") or "")

        lines: List[str] = []
        for stp in steps:
            s_step = _safe_int(stp.get("step", 0))
            enc = str(stp.get("encounter", ""))
            scn = str(stp.get("scene", ""))
            res = str(stp.get("result", ""))
            ch = str(stp.get("choice", ""))
            dd = str(stp.get("difficulty", ""))
            score = _safe_int(stp.get("score", 0))
            target = _safe_int(stp.get("target", 0))
            mark = "✅" if res == "WIN" else "❌"
            lines.append(f"{mark} **{s_step}** — `{scn}` / **{enc}** ({dd}) — {_choice_label(ch)} — {score}/{target}")

        desc = (
            f"👤 <@{self.discord_id}> • 🎴 `{self.code_vip}`\n"
            f"🪪 **{self.pseudo}**\n"
            f"📚 **{arc}**\n\n"
            + ("📜 **Résumé**\n" + "\n".join(lines) if lines else "📜 (Aucun log)")
            + f"\n\n💰 Gain: **+{money_total} Hunt$**\n"
              f"✨ XP: **+{xp_total}**\n"
              f"❤️ HP fin: **{hp_end}**\n"
        )
        if jail_h > 0:
            desc += f"\n🚔 Prison: **{jail_h}h**"
        if boss_hint:
            desc += f"\n\n👑 Prochaine grosse ombre: **{boss_hint}**"

        e = _mk_embed(f"✅ Daily terminé • {dk}", desc, color=discord.Color.green())

        # Image boss hint si dispo
        img = _img_for(encounter="", boss_hint=boss_hint)
        if img:
            e.set_thumbnail(url=img)

        e.set_footer(text="Mikasa referme ton dossier. 🐾")
        return e

    async def apply_choice(self, interaction: discord.Interaction, choice: str) -> None:
        self._require_loaded()

        # lock visuel anti double clic
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True

        # ACK
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

        # apply via rpg
        new_state, outcome = rpg.apply_daily_choice(
            self.s,
            player_row_i=int(self.player_row_i),
            player=dict(self.player),
            state=dict(self.state),
            discord_id=self.discord_id,
            choice=choice
        )

        # fini
        if outcome.get("finished"):
            for c in self.children:
                c.disabled = True
            try:
                await interaction.message.edit(embed=self.build_finished_embed(outcome), view=self)
            except Exception:
                pass
            await interaction.followup.send(catify("✅ Daily terminé. Résumé affiché."), ephemeral=True)
            return

        # continue
        self.state = new_state or self.state
        self._refresh_questions_button()

        # réactive boutons
        for item in self.children:
            if isinstance(item, HuntDailyChoiceButton) or isinstance(item, HuntDailyCloseButton) or isinstance(item, HuntDailyQuestionsButton):
                item.disabled = False
        self._refresh_questions_button()

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        # feedback
        mark = str(outcome.get("mark", ""))
        win = bool(outcome.get("win", False))
        score = _safe_int(outcome.get("score", 0))
        target = _safe_int(outcome.get("target", 0))
        money = _safe_int(outcome.get("money_delta", 0))
        xp = _safe_int(outcome.get("xp_delta", 0))
        hp = _safe_int(outcome.get("hp", 0))
        hp_delta = _safe_int(outcome.get("hp_delta", 0))
        jail_h = _safe_int(outcome.get("jail_hours", 0))

        msg = f"{mark} {'Réussi' if win else 'Raté'} — {score}/{target} • 💰+{money} • ✨+{xp} • ❤️{hp} ({hp_delta:+d})"
        if jail_h > 0:
            msg += f" • 🚔 prison {jail_h}h"
        await interaction.followup.send(catify(msg), ephemeral=True)

    async def open_questions(self, interaction: discord.Interaction) -> None:
        """
        UI “Questions PNJ”.
        - Pour l’instant: 3 questions génériques + enregistrement d’un 'clue' dans state_json si tu ajoutes rpg.daily_add_clue.
        - SAFE: si daily_add_clue n’existe pas -> pas de crash.
        """
        self._require_loaded()
        pending = (self.state or {}).get("pending") or {}
        npc = str(pending.get("npc", "") or "").strip()
        if not npc:
            return await interaction.response.send_message(catify("😾 Aucun PNJ à questionner ici."), ephemeral=True)

        await interaction.response.send_message(
            embed=_mk_embed(
                "❓ Questions",
                f"🗣️ PNJ: **{npc}**\n\nChoisis une question :",
                color=discord.Color.purple()
            ),
            view=HuntQuestionsPickView(parent=self, npc=npc),
            ephemeral=True
        )


class HuntDailyChoiceButton(ui.Button):
    def __init__(self, *, label: str, choice: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        v: HuntDailyView = self.view  # type: ignore
        await v.apply_choice(interaction, self.choice)

class HuntDailyQuestionsButton(ui.Button):
    def __init__(self):
        super().__init__(label="❓ Questions", style=discord.ButtonStyle.secondary, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        v: HuntDailyView = self.view  # type: ignore
        await v.open_questions(interaction)

class HuntDailyCloseButton(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Daily fermé.", embed=None, view=self.view)


# ==========================================================
# Questions View (light, safe)
# ==========================================================
GENERIC_QUESTIONS = [
    ("Qui es-tu ?", "q_who"),
    ("Que caches-tu ici ?", "q_hide"),
    ("Donne-moi une piste utile.", "q_clue"),
]

class HuntQuestionsPickView(ui.View):
    def __init__(self, *, parent: HuntDailyView, npc: str):
        super().__init__(timeout=4 * 60)
        self.parent = parent
        self.npc = npc

        opts = [discord.SelectOption(label=txt, value=key) for (txt, key) in GENERIC_QUESTIONS]
        self.add_item(HuntQuestionsSelect(opts))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche."), ephemeral=True)
            return False
        return True

class HuntQuestionsSelect(ui.Select):
    def __init__(self, options: List[discord.SelectOption]):
        super().__init__(placeholder="Choisir une question…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: HuntQuestionsPickView = self.view  # type: ignore
        key = self.values[0]

        # Texte narratif simple (tu remplaceras par HUNT_STORY)
        if key == "q_who":
            text = f"🗣️ **{view.npc}** te jauge… « Je suis juste un témoin. Pas un héros. »"
            clue = "npc_identity"
        elif key == "q_hide":
            text = f"🗣️ **{view.npc}** murmure… « Tout le monde ment ici. Même les murs. »"
            clue = "npc_fear"
        else:
            text = f"🗣️ **{view.npc}** lâche une phrase… « Cherche le symbole. Une marque sur le béton. »"
            clue = "npc_clue_symbol"

        # Option: enregistrer un clue dans state_json via rpg.daily_add_clue si tu l’ajoutes
        fn = getattr(rpg, "daily_add_clue", None)
        if callable(fn):
            try:
                fn(view.parent.s, player_row_i=int(view.parent.player_row_i), clue=clue)
            except Exception:
                pass

        for c in view.children:
            c.disabled = True
        await interaction.response.edit_message(
            embed=_mk_embed("✅ Réponse", text + "\n\n*(Indice enregistré.)*" if callable(fn) else text, color=discord.Color.green()),
            view=view
        )
