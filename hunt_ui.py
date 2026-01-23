# hunt_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

import discord
from discord import ui

import hunt_services as hs
import hunt_domain as hd
from services import now_fr, now_iso, PARIS_TZ, display_name, catify


# ==========================================================
# Helpers JSON
# ==========================================================
def _json_load(s: str, default: Any) -> Any:
    try:
        if not s:
            return default
        return json.loads(s)
    except Exception:
        return default


def _json_dump(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _truthy(x: Any) -> bool:
    return str(x or "").strip().lower() in ("1", "true", "yes", "y", "vrai", "oui")


def _fmt_fr(dt) -> str:
    return dt.astimezone(PARIS_TZ).strftime("%d/%m %H:%M")


# ==========================================================
# /hunt avatar
# ==========================================================
class HuntAvatarSelect(ui.Select):
    def __init__(self, view: "HuntAvatarView"):
        options = []
        for a in hd.DIRECTION_AVATARS:
            options.append(
                discord.SelectOption(
                    label=a["label"],
                    value=a["tag"],
                    description=f"[{a['tag']}]"
                )
            )
        super().__init__(
            placeholder="Choisis ton personnage (direction SubUrban)…",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_tag = self.values[0]
        await interaction.response.defer(ephemeral=True)


class HuntAvatarConfirm(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Confirmer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        v: HuntAvatarView = self.view  # type: ignore
        if not v.selected_tag:
            return await interaction.response.send_message("Choisis un avatar d’abord 🙂", ephemeral=True)

        a = hd.direction_by_tag(v.selected_tag)
        if not a:
            return await interaction.response.send_message("Avatar invalide.", ephemeral=True)

        # save avatar in sheet
        hs.set_avatar(v.s, discord_id=v.discord_id, avatar_tag=a["tag"], avatar_url=a.get("url", ""))

        # public announce
        try:
            pub = discord.Embed(
                title="🎭 Nouveau personnage Hunt",
                description=f"{interaction.user.mention} a choisi **[{a['tag']}]**",
                color=discord.Color.gold(),
            )
            if a.get("url"):
                pub.set_thumbnail(url=a["url"])
            pub.set_footer(text="Mikasa griffonne le choix dans le registre. 🐾")
            await interaction.channel.send(embed=pub)
        except Exception:
            pass

        # disable panel
        for item in v.children:
            item.disabled = True

        # private confirm
        e = discord.Embed(
            title="✅ Avatar choisi",
            description=f"Tu joueras désormais en **[{a['tag']}]**.\nNom affiché: **{display_name(v.pseudo)} [{a['tag']}]**",
            color=discord.Color.green(),
        )
        if a.get("url"):
            e.set_thumbnail(url=a["url"])
        e.set_footer(text="Mikasa approuve d’un petit hochement de tête. 🐾")
        await interaction.response.edit_message(embed=e, view=v)


class HuntAvatarClose(ui.Button):
    def __init__(self):
        super().__init__(label="✅ Fermer", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        v: HuntAvatarView = self.view  # type: ignore
        for item in v.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Panneau fermé.", embed=None, view=v)


class HuntAvatarView(ui.View):
    """
    Pas de timeout: le choix d'avatar n'est pas pressé.
    (Discord peut quand même invalider une view si le bot redémarre.)
    """
    def __init__(self, *, services, discord_id: int, code_vip: str, pseudo: str):
        super().__init__(timeout=None)
        self.s = services
        self.discord_id = discord_id
        self.code_vip = code_vip
        self.pseudo = pseudo
        self.selected_tag: Optional[str] = None

        self.add_item(HuntAvatarSelect(self))
        self.add_item(HuntAvatarConfirm())
        self.add_item(HuntAvatarClose())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre `/hunt avatar`."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        e = discord.Embed(
            title="🎭 /hunt avatar",
            description=(
                f"👤 **{display_name(self.pseudo)}** • `{self.code_vip}`\n\n"
                "Choisis ton personnage de la direction SubUrban.\n"
                "Ton nom sera affiché comme : **Pseudo [MAI]**.\n\n"
                "✅ Aucun chrono ici. Prends ton temps."
            ),
            color=discord.Color.dark_purple(),
        )
        e.set_footer(text="Mikasa sort les fiches perso. 🐾")
        return e


def build_avatar_panel(*, services, discord_id: int, code_vip: str, pseudo: str) -> Tuple[discord.Embed, discord.ui.View]:
    view = HuntAvatarView(services=services, discord_id=discord_id, code_vip=code_vip, pseudo=pseudo)
    return view.build_embed(), view


# ==========================================================
# /hunt daily
# ==========================================================
class HuntDailyView(ui.View):
    """
    - Sauvegarde après CHAQUE action (state_json + step)
    - Pas de chrono de décision (timeout=None), mais Discord reste capricieux si redémarrage
    - Anti-retour arrière: on incrémente step côté sheet
    """
    def __init__(
        self,
        *,
        services,
        discord_id: int,
        code_vip: str,
        player_row_i: int,
        player: Dict[str, Any],
        daily_row_i: int,
        daily_row: Dict[str, Any],
        tester_bypass: bool,
    ):
        super().__init__(timeout=None)
        self.s = services
        self.discord_id = discord_id
        self.code_vip = code_vip

        self.player_row_i = player_row_i
        self.player = player

        self.daily_row_i = daily_row_i
        self.daily_row = daily_row

        self.tester_bypass = tester_bypass

        raw = str(daily_row.get("state_json", "") or "").strip()
        self.state: Dict[str, Any] = _json_load(raw, {}) or {}
        if not self.state:
            self.state = hd.new_daily_state(player)
            self._touch_log("🌫️ Mikasa ouvre le carnet Hunt. Un bruit dans l’ombre…")

        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton /hunt daily."), ephemeral=True)
            return False
        return True

    # ---------- render ----------
    def build_embed(self) -> discord.Embed:
        avatar_tag = str(self.player.get("avatar_tag", "") or "").strip().upper()
        avatar_url = str(self.player.get("avatar_url", "") or "").strip()

        hp = _safe_int(self.state.get("player_hp"), 20)
        hpmax = _safe_int(self.state.get("player_hp_max"), 20)

        enemy = self.state.get("enemy", {}) or {}
        ehp = _safe_int(enemy.get("hp"), 0)
        ehpmax = _safe_int(enemy.get("hp_max"), 0)

        title_name = display_name(self.player.get("pseudo", "") or "")
        if avatar_tag:
            title_name = f"{title_name} [{avatar_tag}]"

        e = discord.Embed(
            title="🗺️ HUNT • Daily",
            description=(
                f"🎭 **{title_name}**\n"
                f"🏷️ `{self.code_vip}`\n"
                f"🕰️ {_fmt_fr(now_fr())} (FR)\n\n"
                f"📜 {self.state.get('scene', '')}"
            ),
            color=discord.Color.dark_purple(),
        )

        if avatar_url:
            e.set_thumbnail(url=avatar_url)

        e.add_field(name="❤️ PV", value=f"**{hp}/{hpmax}**", inline=True)
        e.add_field(name="👹 Ennemi", value=f"**{enemy.get('name','?')}**\nPV **{ehp}/{ehpmax}**", inline=True)

        logs = (self.state.get("log", []) or [])[-8:]
        if logs:
            e.add_field(name="🧾 Journal", value="\n".join(logs), inline=False)

        if bool(self.state.get("done")):
            xp = _safe_int(self.state.get("reward_xp"), 0)
            dol = _safe_int(self.state.get("reward_dollars"), 0)
            died = bool(self.state.get("died"))
            jailed = bool(self.state.get("jailed"))
            badge = "🏁 Victoire" if (not died and not jailed) else ("💀 KO" if died else "⛓️ Prison")
            e.add_field(name="✅ Résultat", value=f"**{badge}**\n+{dol} Hunt$ • +{xp} XP", inline=False)

        e.set_footer(text="Chaque choix sauvegarde. Pas de retour arrière. 🐾")
        return e

    def _sync_buttons(self) -> None:
        done = bool(self.state.get("done"))
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id != "hunt_close":
                item.disabled = done

    # ---------- persistence ----------
    def _touch_log(self, line: str) -> None:
        arr = self.state.get("log", [])
        if not isinstance(arr, list):
            arr = []
        arr.append(str(line))
        self.state["log"] = arr[-30:]

    async def _save(self) -> None:
        # step anti-retour
        step = _safe_int(self.daily_row.get("step"), 0) + 1
        self.daily_row["step"] = step
        hs.save_daily_state(self.s, self.daily_row_i, step=step, state=self.state)

    async def _finalize_if_done(self) -> None:
        if not bool(self.state.get("done")):
            return

        # mark player "last_daily_date" (bloque la participation)
        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "last_daily_date", hs.date_key_fr())
        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "updated_at", now_iso())

        # totals
        total_runs = _safe_int(self.player.get("total_runs"), 0) + 1
        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "total_runs", total_runs)

        died = bool(self.state.get("died"))
        jailed = bool(self.state.get("jailed"))

        if died:
            total_deaths = _safe_int(self.player.get("total_deaths"), 0) + 1
            self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "total_deaths", total_deaths)
        if (not died) and (not jailed):
            total_wins = _safe_int(self.player.get("total_wins"), 0) + 1
            self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "total_wins", total_wins)

        # money + xp
        dol = _safe_int(self.state.get("reward_dollars"), 0)
        xp = _safe_int(self.state.get("reward_xp"), 0)

        cur_d = _safe_int(self.player.get("hunt_dollars"), 0)
        cur_xp = _safe_int(self.player.get("xp"), 0)
        cur_total = _safe_int(self.player.get("xp_total"), 0)

        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "hunt_dollars", max(0, cur_d + dol))
        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "xp", max(0, cur_xp + xp))
        self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "xp_total", max(0, cur_total + xp))

        # prison
        if jailed:
            hours = _safe_int(self.state.get("jail_hours"), 6)
            hours = max(1, min(hs.MAX_JAIL_HOURS, hours))
            until = now_fr() + timedelta(hours=hours)
            self.s.update_cell_by_header(hs.T_PLAYERS, self.player_row_i, "jail_until", until.astimezone(PARIS_TZ).isoformat(timespec="seconds"))

        # finish daily row
        dmg_taken = max(0, _safe_int(self.state.get("dmg_taken"), 0))
        summary = " | ".join((self.state.get("log", []) or [])[-4:])
        hs.finish_daily(
            self.s,
            self.daily_row_i,
            summary=summary,
            xp=xp,
            dollars=dol,
            dmg=dmg_taken,
            died=died,
            jailed=jailed,
        )

    # ---------- buttons ----------
    @ui.button(label="🗡️ Attaquer", style=discord.ButtonStyle.danger, custom_id="hunt_attack")
    async def btn_attack(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hd.apply_attack(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="🩹 Se soigner", style=discord.ButtonStyle.primary, custom_id="hunt_heal")
    async def btn_heal(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hd.apply_heal(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="👜 Voler", style=discord.ButtonStyle.secondary, custom_id="hunt_steal")
    async def btn_steal(self, interaction: discord.Interaction, button: ui.Button):
        self.state = hd.apply_steal(self.state, self.player)
        await self._save()
        await self._finalize_if_done()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success, custom_id="hunt_close")
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Hunt daily fermé.", embed=None, view=self)


# ==========================================================
# Builders called by your command handlers
# ==========================================================
def build_daily_panel(
    *,
    services,
    discord_id: int,
    code_vip: str,
    pseudo: str,
    is_employee: bool,
) -> Tuple[discord.Embed, discord.ui.View]:
    """
    À appeler depuis /hunt daily.
    - crée/refresh player
    - vérifie prison + quota (sauf testers)
    - crée/reprend la ligne HUNT_DAILY du jour
    - renvoie (embed, view)
    """
    # player upsert
    player_row_i, player = hs.upsert_player(
        services,
        discord_id=discord_id,
        code_vip=code_vip,
        pseudo=pseudo,
        is_employee=is_employee,
    )

    tester_bypass = hs.is_tester(discord_id)

    ok, msg = hs.can_run_daily(player, dt=now_fr())
    if (not ok) and (not tester_bypass):
        e = discord.Embed(
            title="⛓️ HUNT • Daily indisponible",
            description=msg,
            color=discord.Color.red(),
        )
        e.set_footer(text="Mikasa referme le carnet. 🐾")
        return e, ui.View(timeout=10)

    # daily row
    dk = hs.date_key_fr()
    daily_row_i, daily_row = hs.ensure_daily(services, discord_id=discord_id, code_vip=hs.normalize_code(code_vip), date_key=dk)

    # build view (resume state if exists)
    view = HuntDailyView(
        services=services,
        discord_id=discord_id,
        code_vip=hs.normalize_code(code_vip),
        player_row_i=player_row_i,
        player=player,
        daily_row_i=daily_row_i,
        daily_row=daily_row,
        tester_bypass=tester_bypass,
    )

    # save initial state if it was empty
    if not str(daily_row.get("state_json", "") or "").strip():
        hs.save_daily_state(services, daily_row_i, step=0, state=view.state)

    return view.build_embed(), view
