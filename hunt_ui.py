# hunt_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple

import discord
from discord import ui

import hunt_rpg as rpg
from services import catify, now_fr, now_iso


# ==========================================================
# Helpers embeds
# ==========================================================
def _mk_embed(
    title: str,
    desc: str,
    *,
    color: discord.Color = discord.Color.blurple(),
    thumb: str = "",
    footer: str = "",
) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    if thumb:
        e.set_thumbnail(url=thumb)
    if footer:
        e.set_footer(text=footer)
    return e


def _fmt_step_bar(done_steps: int, max_steps: int) -> str:
    # done_steps = 0..max_steps
    done_steps = max(0, min(int(done_steps), int(max_steps)))
    max_steps = max(1, int(max_steps))
    return "🧩 " + ("■" * done_steps) + ("□" * (max_steps - done_steps)) + f"  ({done_steps}/{max_steps})"


def _pending_text(p: Dict[str, Any]) -> str:
    scene = str(p.get("scene", "rue"))
    encounter = str(p.get("encounter", "inconnu"))
    kind = str(p.get("kind", "ENEMY"))
    diff = str(p.get("difficulty", "MED"))
    npc = str(p.get("npc", "") or "").strip()

    lines = [
        f"📍 **Paysage** : `{scene}`",
        f"👁️ **Rencontre** : **{encounter}** ({kind}, {diff})",
    ]
    if npc:
        lines.append(f"🧑‍🦱 **PNJ** : *{npc}*")
    return "\n".join(lines)


# ==========================================================
# HUB (optionnel / safe)
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
            f"🪪 Pseudo : **{self.pseudo}**\n\n"
            "Choisis une action :\n"
            "• 🗺️ Daily RPG (multi-encounters)\n"
            "• 🎒 Inventaire (placeholder)\n"
            "• 🛒 Shop (placeholder)\n"
        )
        return _mk_embed(
            "🧭 HUNT • Hub",
            desc,
            color=discord.Color.dark_purple(),
            footer="Mikasa ouvre ton dossier… 🐾",
        )

    @ui.button(label="🗺️ Daily RPG", style=discord.ButtonStyle.primary)
    async def btn_daily(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntDailyView(sheets=self.s, discord_id=self.discord_id, code_vip=self.code_vip, pseudo=self.pseudo)
        await view.load()
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @ui.button(label="🎒 Inventaire", style=discord.ButtonStyle.secondary)
    async def btn_inv(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(catify("🐾 Inventaire pas encore branché."), ephemeral=True)

    @ui.button(label="🛒 Shop", style=discord.ButtonStyle.secondary)
    async def btn_shop(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(catify("🐾 Shop pas encore branché."), ephemeral=True)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="✅ Hub fermé.", embed=None, view=self)


# ==========================================================
# AVATAR UI (optionnel)
# ==========================================================
AVATARS: List[Tuple[str, str]] = [
    ("MAI", ""),
    ("ROXY", ""),
    ("DODO", ""),
    ("THIB", ""),
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
            return await interaction.response.send_message("❌ Player introuvable.", ephemeral=True)

        url = ""
        for tag, u in AVATARS:
            if tag == v.selected_tag:
                url = u
                break

        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "avatar_tag", v.selected_tag)
        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "avatar_url", url)
        v.s.update_cell_by_header(rpg.T_PLAYERS, row_i, "updated_at", now_iso())

        for c in v.children:
            c.disabled = True

        e = _mk_embed(
            "✅ Avatar enregistré",
            f"Ton tag est maintenant **[{v.selected_tag}]**.",
            color=discord.Color.green(),
            thumb=url,
            footer="Mikasa colle ton badge. 🐾",
        )
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
        self.add_item(HuntCloseButton(label="✅ Fermer"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(catify("😾 Pas touche."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        desc = (
            "Choisis un perso SubUrban.\n"
            "Ton tag apparaîtra en **[MAI]**, **[ROXY]**, etc.\n\n"
            + (f"Sélection : **{self.selected_tag}**" if self.selected_tag else "Sélection : *(aucune)*")
        )
        return _mk_embed("🎭 Choix d’avatar", desc, color=discord.Color.purple(), footer="Mikasa sort la boîte d’étiquettes. 🐾")


# ==========================================================
# DAILY RPG UI (multi-encounters)
# - compatible avec TON hunt_rpg.py :
#   - begin_or_resume_daily(...)
#   - apply_daily_choice(...)
# ==========================================================
CHOICES: List[Tuple[str, str, discord.ButtonStyle]] = [
    ("🧭 Explorer",  "explore",    discord.ButtonStyle.secondary),
    ("💬 Négocier",  "negotiate",  discord.ButtonStyle.primary),
    ("⚔️ Attaquer",  "fight",      discord.ButtonStyle.danger),
    ("🧤 Voler",     "steal",      discord.ButtonStyle.secondary),
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
        self.state: Dict[str, Any] = {}

        self._busy = False  # anti double clic

        # boutons actions
        for label, key, style in CHOICES:
            self.add_item(HuntDailyChoiceButton(label=label, choice_key=key, style=style))

        # debug + close
        self.add_item(HuntDailyStatusButton())
        self.add_item(HuntCloseButton(label="✅ Fermer"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre Daily."), ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

    async def load(self) -> None:
        """
        À appeler AVANT d'envoyer la view.
        """
        row_i, player, state = rpg.begin_or_resume_daily(self.s, discord_id=self.discord_id)
        self.player_row_i = row_i
        self.player = player
        self.state = state or {}

    def build_embed(self) -> discord.Embed:
        st = self.state or {}

        # si state vide => daily terminé / cleared
        if not st or not st.get("date_key"):
            desc = (
                f"👤 <@{self.discord_id}> • `{self.code_vip}`\n\n"
                "✅ Daily terminé (ou state_json vide).\n"
                "Relance la commande si besoin."
            )
            return _mk_embed("🗺️ Daily RPG", desc, color=discord.Color.green(), footer="Mikasa referme le carnet. 🐾")

        dk = str(st.get("date_key", ""))
        arc = str(st.get("arc", ""))
        hp = int(st.get("hp", 100) or 100)
        hp_max = int(st.get("hp_max", 100) or 100)
        step = int(st.get("step", 1) or 1)
        max_steps = int(st.get("max_steps", 3) or 3)

        # done_steps = step-1 (car step = étape actuelle à jouer)
        done_steps = max(0, step - 1)

        pending = st.get("pending") or {}
        pending_block = _pending_text(pending)

        desc = (
            f"👤 <@{self.discord_id}> • 🎴 `{self.code_vip}`\n"
            f"🏷️ Arc : **{arc}**\n"
            f"❤️ HP : **{hp}/{hp_max}**\n"
            f"{_fmt_step_bar(done_steps, max_steps)}\n\n"
            f"{pending_block}\n\n"
            "Choisis une action. Chaque clic est enregistré dans `state_json`."
        )

        e = _mk_embed(
            f"🗺️ Daily RPG • {dk}",
            desc,
            color=discord.Color.blurple(),
            footer="Aucun retour arrière. Mikasa note tout. 🐾",
        )

        # mini log (2 dernières)
        logs = st.get("log") or []
        if isinstance(logs, list) and logs:
            last = logs[-2:] if len(logs) >= 2 else logs
            lines = []
            for x in last:
                try:
                    sstep = x.get("step", "?")
                    enc = x.get("encounter", "?")
                    ch = x.get("choice", "?")
                    res = x.get("result", "?")
                    lines.append(f"• #{sstep} **{enc}** → `{ch}` = **{res}**")
                except Exception:
                    continue
            if lines:
                e.add_field(name="📜 Derniers événements", value="\n".join(lines), inline=False)

        return e

    async def _disable_all(self, interaction: discord.Interaction, *, embed: Optional[discord.Embed] = None):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def apply_choice(self, interaction: discord.Interaction, choice_key: str):
        if self._busy:
            return await interaction.followup.send(catify("😾 Doucement. Un choix est déjà en cours…"), ephemeral=True)
        self._busy = True

        try:
            if self.player_row_i is None or self.player is None:
                await self.load()

            if not self.state or not self.state.get("date_key"):
                return await interaction.followup.send(catify("😾 Daily indisponible. Relance la commande."), ephemeral=True)

            # appelle TON rpg.apply_daily_choice
            new_state, outcome = rpg.apply_daily_choice(
                self.s,
                player_row_i=int(self.player_row_i),
                player=dict(self.player),
                state=dict(self.state),
                discord_id=self.discord_id,
                choice=choice_key,
            )

            finished = bool(outcome.get("finished")) if isinstance(outcome, dict) else False

            if finished:
                # state_json a été clear côté rpg
                self.state = {}
                final_embed = self._build_finished_embed(outcome)
                await self._disable_all(interaction, embed=final_embed)
                return await interaction.followup.send(catify("✅ Daily terminé. Récompenses créditées."), ephemeral=True)

            # mise à jour locale
            self.state = new_state or self.state

            # edit du message principal
            try:
                await interaction.message.edit(embed=self.build_embed(), view=self)
            except Exception:
                pass

            # note ephemeral
            note = self._format_outcome_note(outcome)
            await interaction.followup.send(note, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(catify(f"❌ Erreur: {type(e).__name__}\n{e}"), ephemeral=True)
        finally:
            self._busy = False

    def _format_outcome_note(self, outcome: Dict[str, Any]) -> str:
        mark = str(outcome.get("mark", ""))
        score = outcome.get("score", None)
        target = outcome.get("target", None)
        hp_delta = int(outcome.get("hp_delta", 0) or 0)
        money = int(outcome.get("money_delta", 0) or 0)
        xp = int(outcome.get("xp_delta", 0) or 0)
        jail = int(outcome.get("jail_hours", 0) or 0)

        parts = [f"{mark} Réponse enregistrée."]
        if score is not None and target is not None:
            parts.append(f"🎲 Score: **{score}** / cible **{target}**")
        if hp_delta:
            parts.append(f"❤️ HP: **{hp_delta:+d}**")
        parts.append(f"💵 +{money} $HUNT")
        parts.append(f"✨ +{xp} XP")
        if jail > 0:
            parts.append(f"🚓 Jail: **{jail}h**")
        return "\n".join(parts)

    def _build_finished_embed(self, outcome: Dict[str, Any]) -> discord.Embed:
        dk = str(outcome.get("date_key", "") or "")
        arc = str(outcome.get("arc", "") or "")
        boss_hint = str(outcome.get("boss_hint", "") or "")
        hp_end = int(outcome.get("hp_end", 0) or 0)
        money_total = int(outcome.get("money_total", 0) or 0)
        xp_total = int(outcome.get("xp_total", 0) or 0)
        jail_hours = int(outcome.get("jail_hours", 0) or 0)

        desc = (
            f"👤 <@{self.discord_id}> • `{self.code_vip}`\n"
            f"📅 Date : **{dk}**\n"
            f"🏷️ Arc : **{arc}**\n\n"
            f"💵 Gain total : **+{money_total}** $HUNT\n"
            f"✨ XP total : **+{xp_total}**\n"
            f"❤️ HP fin : **{hp_end}**\n"
            + (f"🚓 Jail : **{jail_hours}h**\n" if jail_hours > 0 else "")
            + (f"\n👑 Boss lié à l’arc : **{boss_hint}**" if boss_hint else "")
        )
        return _mk_embed(
            "✅ Daily RPG terminé",
            desc,
            color=discord.Color.green(),
            footer="Mikasa tamponne la feuille de route. 🐾",
        )


class HuntDailyChoiceButton(ui.Button):
    def __init__(self, *, label: str, choice_key: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.choice_key = choice_key

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        # ACK 1 seule fois (safe)
        await interaction.response.defer(ephemeral=True)
        await view.apply_choice(interaction, self.choice_key)


class HuntDailyStatusButton(ui.Button):
    """
    Bouton debug : affiche state_json brut (coupé) pour vérifier que tout se remplit.
    """
    def __init__(self):
        super().__init__(label="📌 Status", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        await interaction.response.defer(ephemeral=True)

        row_i, player = rpg.get_player_row(view.s, view.discord_id)
        if not row_i or not player:
            return await interaction.followup.send("❌ Player introuvable.", ephemeral=True)

        raw = str(player.get("state_json", "") or "")
        if not raw.strip():
            return await interaction.followup.send("✅ state_json vide (daily terminé ou non lancé).", ephemeral=True)

        txt = raw if len(raw) <= 1700 else (raw[:1700] + "…")
        await interaction.followup.send(f"```json\n{txt}\n```", ephemeral=True)


# ==========================================================
# Bouton fermer générique
# ==========================================================
class HuntCloseButton(ui.Button):
    def __init__(self, *, label: str = "✅ Fermer"):
        super().__init__(label=label, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        for c in self.view.children:
            c.disabled = True
        await interaction.response.edit_message(content="✅ Fermé.", embed=None, view=self.view)
