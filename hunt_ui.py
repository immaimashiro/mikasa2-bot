# hunt_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple

import discord
from discord import ui

import hunt_rpg as rpg
from services import catify, now_fr, now_iso

# ==========================================================
# Embeds helpers
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


# ==========================================================
# HUNT HUB (optionnel)
# - safe: Shop/Inventory placeholders pour éviter les crashs
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
        await interaction.response.send_message(
            catify("🐾 Inventaire pas encore branché. On le reconnecte après le RPG."),
            ephemeral=True,
        )

    @ui.button(label="🛒 Shop", style=discord.ButtonStyle.secondary)
    async def btn_shop(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            catify("🐾 Shop pas encore branché. On le reconnecte après le RPG."),
            ephemeral=True,
        )

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="✅ Hub fermé.", embed=None, view=self)


# ==========================================================
# AVATAR UI (optionnel)
# - si tu l'utilises dans /hunt avatar
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
        super().__init__(
            placeholder="Choisis ton personnage…",
            options=opts,
            min_values=1,
            max_values=1,
        )
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
            + (f"Sélection: **{self.selected_tag}**" if self.selected_tag else "Sélection: *(aucune)*")
        )
        return _mk_embed("🎭 Choix d’avatar", desc, color=discord.Color.purple(), footer="Mikasa sort la boîte d’étiquettes. 🐾")


# ==========================================================
# DAILY RPG (multi-encounters) — UI complète
# - se base sur hunt_rpg.py :
#   - get_player_row
#   - daily_begin_or_resume(...)
#   - daily_apply_choice(...)
#   - (daily_finalize est appelé par rpg quand fini)
# ==========================================================
CHOICES: List[Tuple[str, str, discord.ButtonStyle]] = [
    ("🧭 Explorer",  "explore",    discord.ButtonStyle.secondary),
    ("💬 Négocier",  "negotiate",  discord.ButtonStyle.primary),
    ("⚔️ Attaquer",  "fight",      discord.ButtonStyle.danger),
    ("🧤 Voler",     "steal",      discord.ButtonStyle.secondary),
]

def _fmt_pending(p: Dict[str, Any]) -> str:
    scene = str(p.get("scene", "rue"))
    encounter = str(p.get("encounter", "inconnu"))
    kind = str(p.get("kind", "ENEMY"))
    diff = str(p.get("difficulty", "MED"))
    return f"📍 **Paysage**: `{scene}`\n👁️ **Rencontre**: **{encounter}** ({kind}, {diff})"

def _fmt_step_bar(step: int, max_steps: int) -> str:
    # 1..max
    done = max(0, step - 1)
    return "🧩 " + ("■" * done) + ("□" * max(0, max_steps - done)) + f"  ({done}/{max_steps})"

class HuntDailyView(ui.View):
    """
    View daily robuste:
    - load() -> begin_or_resume (state_json créé/relancé)
    - boutons -> apply_choice -> edit message + followup note
    - si finished -> affiche un résumé et désactive les boutons
    """
    def __init__(self, *, sheets, discord_id: int, code_vip: str, pseudo: str):
        super().__init__(timeout=12 * 60)
        self.s = sheets
        self.discord_id = int(discord_id)
        self.code_vip = str(code_vip)
        self.pseudo = str(pseudo)

        self.player_row_i: Optional[int] = None
        self.player: Optional[Dict[str, Any]] = None
        self.state: Dict[str, Any] = {}

        self._busy = False  # anti double click

        # boutons
        for label, key, style in CHOICES:
            self.add_item(HuntDailyChoiceButton(label=label, choice_key=key, style=style))
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
        row_i, player, state = rpg.daily_begin_or_resume(
            self.s,
            discord_id=self.discord_id,
            vip_code=self.code_vip,
            pseudo=self.pseudo,
        )
        self.player_row_i = row_i
        self.player = player
        self.state = state or {}

    def build_embed(self) -> discord.Embed:
        st = self.state or {}
        dk = str(st.get("date_key", ""))
        arc = str(st.get("arc", ""))
        step = int(st.get("step", 1) or 1)
        max_steps = int(st.get("max_steps", 3) or 3)
        hp = int(st.get("hp", 100) or 100)
        hp_max = int(st.get("hp_max", 100) or 100)
        pending = st.get("pending") or {}

        # si jamais state vide (daily terminé/clear) -> message safe
        if not st or not dk:
            desc = (
                f"👤 <@{self.discord_id}> • `{self.code_vip}`\n\n"
                "✅ Daily terminé (ou non initialisé).\n"
                "Relance la commande si besoin."
            )
            return _mk_embed("🗺️ Daily RPG", desc, color=discord.Color.green(), footer="Mikasa referme le carnet. 🐾")

        desc = (
            f"👤 <@{self.discord_id}> • `{self.code_vip}`\n"
            f"🏷️ Arc: **{arc}**\n"
            f"❤️ HP: **{hp}/{hp_max}**\n"
            f"{_fmt_step_bar(step, max_steps)}\n\n"
            f"{_fmt_pending(pending)}\n\n"
            "Choisis une action. (Chaque clic est sauvegardé dans `state_json`.)"
        )
        e = _mk_embed(
            f"🗺️ Daily RPG • {dk}",
            desc,
            color=discord.Color.blurple(),
            footer="Aucun retour arrière. Mikasa note tout. 🐾",
        )

        # petit journal (2 dernières entrées)
        logs = st.get("log") or []
        if isinstance(logs, list) and logs:
            last = logs[-2:] if len(logs) >= 2 else logs
            lines = []
            for x in last:
                try:
                    sstep = x.get("step", "?")
                    res = x.get("result", "?")
                    enc = x.get("encounter", "?")
                    ch = x.get("choice", "?")
                    lines.append(f"• #{sstep} **{enc}** → `{ch}` = **{res}**")
                except Exception:
                    continue
            if lines:
                e.add_field(name="📜 Derniers événements", value="\n".join(lines), inline=False)

        return e

    async def _edit_message(self, interaction: discord.Interaction) -> None:
        # rebuild: ici on ne change pas dynamiquement les items, on désactive seulement si fini
        await interaction.message.edit(embed=self.build_embed(), view=self)

    async def _disable_all(self, interaction: discord.Interaction, *, content: str = ""):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(content=content or None, embed=self.build_embed(), view=self)
        except Exception:
            pass

    async def apply_choice(self, interaction: discord.Interaction, choice_key: str):
        if self._busy:
            return await interaction.followup.send(catify("😾 Doucement. Un choix est déjà en cours…"), ephemeral=True)
        self._busy = True

        try:
            if self.player_row_i is None or self.player is None:
                # sécurité si load() pas appelé
                await self.load()

            # si state vide -> refuse propre
            if not self.state or not self.state.get("date_key"):
                return await interaction.followup.send(catify("😾 Daily indisponible. Relance la commande."), ephemeral=True)

            # exécute la logique rpg
            new_state, outcome = rpg.daily_apply_choice(
                self.s,
                player_row_i=int(self.player_row_i),
                player=self.player,
                state=self.state,
                discord_id=self.discord_id,
                choice=choice_key,
            )

            # daily_apply_choice peut retourner {} si terminé (state cleared)
            finished = bool(outcome.get("finished")) if isinstance(outcome, dict) else False

            if finished:
                # on marque localement pour afficher un résumé propre
                self.state = {}  # state cleared côté sheet déjà
                summary = self._build_finished_embed(outcome)
                await self._disable_all(interaction, content="")
                await interaction.message.edit(embed=summary, view=self)

                # followup
                return await interaction.followup.send(
                    catify("✅ Daily terminé. Récompenses créditées."),
                    ephemeral=True,
                )

            # sinon: update state local + refresh embed
            self.state = new_state or self.state

            # message note
            note = self._format_outcome_line(outcome)

            # edit message principal
            try:
                await self._edit_message(interaction)
            except Exception:
                pass

            await interaction.followup.send(note, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(catify(f"❌ Erreur: {type(e).__name__}\n{e}"), ephemeral=True)
        finally:
            self._busy = False

    def _format_outcome_line(self, outcome: Dict[str, Any]) -> str:
        res = str(outcome.get("result", ""))
        hp_delta = int(outcome.get("hp_delta", 0) or 0)
        money = int(outcome.get("money_delta", 0) or 0)
        xp = int(outcome.get("xp_delta", 0) or 0)
        jail = int(outcome.get("jail_hours", 0) or 0)
        score = outcome.get("score", None)
        target = outcome.get("target", None)

        parts = [("✅" if res == "WIN" else "❌") + f" Résultat: **{res}**"]
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
        money = int(outcome.get("money_total", 0) or 0)
        xp = int(outcome.get("xp_total", 0) or 0)
        jail = int(outcome.get("jail_hours", 0) or 0)
        hp_end = int(outcome.get("hp_end", 0) or 0)
        arc = str(outcome.get("arc", ""))
        boss_next = str(outcome.get("boss_next", ""))

        desc = (
            f"👤 <@{self.discord_id}> • `{self.code_vip}`\n"
            f"🏷️ Arc: **{arc}**\n\n"
            f"💵 Gain total: **+{money}** $HUNT\n"
            f"✨ XP total: **+{xp}**\n"
            f"❤️ HP fin: **{hp_end}**\n"
            + (f"🚓 Jail: **{jail}h**\n" if jail > 0 else "")
            + (f"\n👑 Boss lié à l’arc: **{boss_next}**" if boss_next else "")
        )

        e = _mk_embed(
            "✅ Daily RPG terminé",
            desc,
            color=discord.Color.green(),
            footer="Mikasa tamponne la feuille de route. 🐾",
        )
        return e


class HuntDailyChoiceButton(ui.Button):
    def __init__(self, *, label: str, choice_key: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.choice_key = choice_key

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        # ACK unique: defer, puis followup + message.edit
        await interaction.response.defer(ephemeral=True)
        await view.apply_choice(interaction, self.choice_key)


class HuntDailyStatusButton(ui.Button):
    """
    Petit bouton “📌 Status” : renvoie le state_json actuel (résumé) en ephemeral
    Utile pour debug si tu veux vérifier que state_json se remplit bien.
    """
    def __init__(self):
        super().__init__(label="📌 Status", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: HuntDailyView = self.view  # type: ignore
        await interaction.response.defer(ephemeral=True)

        if view.player_row_i is None:
            return await interaction.followup.send("❌ State non chargé.", ephemeral=True)

        # relis la ligne player pour afficher le state_json brut (coupé)
        row_i, player = rpg.get_player_row(view.s, view.discord_id)
        if not row_i or not player:
            return await interaction.followup.send("❌ Player introuvable.", ephemeral=True)

        raw = str(player.get("state_json", "") or "")
        if not raw.strip():
            return await interaction.followup.send("✅ state_json vide (daily terminé ou non lancé).", ephemeral=True)

        txt = raw if len(raw) <= 1500 else (raw[:1500] + "…")
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
