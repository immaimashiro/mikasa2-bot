# hunt_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any
import discord
from discord import ui

import hunt_rpg as rpg
from services import catify, now_fr

img = ENCOUNTER_IMAGES.get(encounter) or ENCOUNTER_IMAGES.get(boss_hint)
if img: embed.set_thumbnail(url=img)

# ==========================================================
# Helpers
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
    return mapping.get(choice, choice)

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
    if arc == rpg.ARC_1:
        return "ARC I — Ombres"
    if arc == rpg.ARC_2:
        return "ARC II — Luxus"
    if arc == rpg.ARC_3:
        return "ARC III — Dodo"
    if arc == rpg.ARC_4:
        return "ARC FINAL — Shakir"
    return arc or "ARC ?"


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
# Tu peux remplacer par tes persos + urls
AVATARS: List[Tuple[str, str]] = [
    ("MAI", "https://i.imgur.com/1Q9Z1ZC.png"),
    ("ROXY", "https://i.imgur.com/1Q9Z1ZC.png"),
    ("DODO", "https://i.imgur.com/1Q9Z1ZC.png"),
    ("THIB", "https://i.imgur.com/1Q9Z1ZC.png"),
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

        self.sent_at = now_fr()

        for label, val, style in CHOICES:
            self.add_item(HuntDailyChoiceButton(label=label, choice=val, style=style))
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
        # Crée / reprend le state_json daily
        row_i, player, state = rpg.begin_or_resume_daily(self.s, discord_id=self.discord_id)
        self.player_row_i = row_i
        self.player = player
        self.state = state
        self.sent_at = now_fr()

    def _require_loaded(self) -> None:
        if not self.player_row_i or not self.player or not self.state:
            raise RuntimeError("DailyView not loaded. Call await view.load() before sending.")

    def build_embed(self) -> discord.Embed:
        self._require_loaded()
        st = self.state or {}
        pending = st.get("pending") or {}

        dk = str(st.get("date_key", ""))
        step_next = _safe_int(st.get("step", 1), 1)  # c'est l'étape "courante" à jouer
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
            f"📚 **{arc}**\n"
            f"🧩 Étape **{step_next}/{mx}**\n"
            f"❤️ HP: **{hp}/{hp_max}**\n\n"
            f"📍 **Paysage**: `{scene}`\n"
            f"{kind}: **{encounter}** — {diff}\n"
            + (f"🗣️ PNJ: **{npc}**\n" if npc else "")
            + "\nChoisis une action (aucun retour arrière)."
        )
        e = _mk_embed(f"🗺️ HUNT Daily • {dk}", desc, color=discord.Color.blurple())
        e.set_footer(text="Progression sauvegardée (state_json). Reviens et ça reprend. 🐾")
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
        for st in steps:
            s_step = _safe_int(st.get("step", 0))
            enc = str(st.get("encounter", ""))
            scn = str(st.get("scene", ""))
            res = str(st.get("result", ""))
            ch = str(st.get("choice", ""))
            dd = str(st.get("difficulty", ""))
            score = _safe_int(st.get("score", 0))
            target = _safe_int(st.get("target", 0))
            mark = "✅" if res == "WIN" else "❌"
            lines.append(f"{mark} **{s_step}** — `{scn}` / **{enc}** ({dd}) — {_choice_label(ch)} — {score}/{target}")

        desc = (
            f"👤 <@{self.discord_id}> • 🎴 `{self.code_vip}`\n"
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
        e.set_footer(text="Mikasa referme ton dossier. 🐾")
        return e

    async def _render_edit(self, interaction: discord.Interaction) -> None:
        # refresh embed (ack unique via response.edit_message)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def apply_choice(self, interaction: discord.Interaction, choice: str) -> None:
        self._require_loaded()

        # Anti double clic visuel
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True

        # ACK immédiatement (évite "Interaction failed")
        await self._render_edit(interaction)

        # Re-lire state depuis self.state, appliquer
        new_state, outcome = rpg.apply_daily_choice(
            self.s,
            player_row_i=int(self.player_row_i),
            player=dict(self.player),
            state=dict(self.state),
            discord_id=self.discord_id,
            choice=choice
        )

        # Si fini, outcome est final + state_json cleared
        if outcome.get("finished"):
            for c in self.children:
                c.disabled = True
            try:
                await interaction.message.edit(embed=self.build_finished_embed(outcome), view=self)
            except Exception:
                pass
            await interaction.followup.send(catify("✅ Daily terminé. Résumé affiché."), ephemeral=True)
            return

        # Sinon on continue : update local state
        self.state = new_state or self.state
        self.sent_at = now_fr()

        # Réactiver boutons
        for item in self.children:
            if isinstance(item, HuntDailyChoiceButton):
                item.disabled = False
        for item in self.children:
            if isinstance(item, HuntDailyCloseButton):
                item.disabled = False

        # Edit du message pour afficher la prochaine encounter
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        # Feedback court
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


class HuntDailyChoiceButton(ui.Button):
    def __init__(self, *, label: str, choice: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        v: HuntDailyView = self.view  # type: ignore
        await v.apply_choice(interaction, self.choice)

class HuntDailyCloseButton(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Daily fermé.", embed=None, view=self.view)
