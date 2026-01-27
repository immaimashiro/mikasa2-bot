# hunt_ui.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import discord
from discord import ui
import random
import hunt_data as hda  # ou le nom exact de ton fichier hunt_data.py

import hunt_services as hs
import hunt_domain as hd
from hunt_data import AVATARS, get_avatar, avatar_image_url, rarity_rank, format_player_title

from services import catify, now_iso

# -------------------------
# petits helpers d’edit safe
# -------------------------

async def _edit(interaction: discord.Interaction, *, content: Optional[str] = None, embed: Optional[discord.Embed] = None, view: Optional[discord.ui.View] = None):
    try:
        if interaction.response.is_done():
            await interaction.message.edit(content=content, embed=embed, view=view)
        else:
            await interaction.response.edit_message(content=content, embed=embed, view=view)
    except Exception:
        pass

def _money(n: int) -> str:
    return f"{int(n)} 💵"

def _rarity_label(r: str) -> str:
    r = (r or "").lower().strip()
    return {
        "common": "Common",
        "uncommon": "Uncommon",
        "rare": "Rare",
        "epic": "Epic",
        "legendary": "Legendary",
    }.get(r, r or "Common")

class ShopTabSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        opts = [
            discord.SelectOption(label="🛒 Shop normal", value="NORMAL", description="Objets clean, prix standards."),
            discord.SelectOption(label="🕳️ Marché noir", value="BLACK", description="Plus fort, plus risqué, plus cher."),
        ]
        super().__init__(placeholder="Choisir une boutique…", options=opts, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.active_tab = self.values[0]
        self.v.selected_item_id = None
        await self.v.refresh(interaction)


class ShopItemSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        self.v = view
        super().__init__(placeholder="Chargement…", options=[discord.SelectOption(label="...", value="__none__")])

    def rebuild(self, rows: list[dict]):
        opts: list[discord.SelectOption] = []
        for r in rows[:25]:
            iid = str(r.get("item_id", "")).strip()
            nm = str(r.get("name", iid)).strip()[:90]
            price = str(r.get("price", "")).strip()
            rarity = str(r.get("rarity", "")).strip().upper()
            if not iid:
                continue
            desc = f"{rarity} • {price}$"
            opts.append(discord.SelectOption(label=nm, value=iid, description=desc[:100]))

        if not opts:
            opts = [discord.SelectOption(label="(vide)", value="__none__", description="Aucun item dispo.")]

        self.options = opts
        self.placeholder = "Choisir un item…"
        self.min_values = 1
        self.max_values = 1

    async def callback(self, interaction: discord.Interaction):
        iid = self.values[0]
        if iid == "__none__":
            return await interaction.response.defer(ephemeral=True)
        self.v.selected_item_id = iid
        await self.v.refresh(interaction)


# ==========================================================
# HUB HUNT (message unique, tout se fait dessus)
# ==========================================================
class HuntHubView(ui.View):
    def __init__(self, *, sheets, discord_id: int, code_vip: str, pseudo: str, is_employee: bool):
        super().__init__(timeout=10 * 60)
        self.sheets = sheets
        self.discord_id = int(discord_id)
        self.code_vip = (code_vip or "").strip()
        self.pseudo = (pseudo or "").strip() or self.code_vip
        self.is_employee = bool(is_employee)

        self.p_row_i, self.player = hs.ensure_player(
            sheets,
            discord_id=self.discord_id,
            vip_code=self.code_vip,
            pseudo=self.pseudo,
            is_employee=self.is_employee
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre HUNT."), ephemeral=True)
            return False
        return True

    def build_embed(self)
        e = discord.Embed(
            title="🧭 HUNT — Daily",
            description="Choisis ton action.",
            color=discord.Color.blurple()
        )
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.player
        dollars = hs.player_money_get(row)
        avatar_tag = str(row.get("avatar_tag", "")).strip() or "?"
        ally_tag = str(row.get("ally_tag", "")).strip()
        if ally_tag:
            e.add_field(name="🤝 Allié", value=f"**{ally_tag}**", inline=True)
        else:
            e.add_field(name="🤝 Allié", value="*Aucun*", inline=True)
        wk = hs.week_key_friday_17h(now_fr()) if hasattr(hs, "week_key_friday_17h") else hs.hunt_week_key()
        roll_wk = hs.ally_roll_week_key_get(row)
        if roll_wk == wk and not ally_tag:
            e.add_field(name="🎲 Recrutement", value="Tenté cette semaine (échec).", inline=True)

        e.add_field(name="🤝 Allié", value=(ally if ally else "Aucun"), inline=False)

        e = discord.Embed(
            title="🗺️ HUNT",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"🎴 VIP: `{self.code_vip}`\n"
                f"🧍 Avatar: **{avatar_tag}**\n"
                f"💰 Argent: **{_money(dollars)}**\n\n"
                "Choisis une action :"
            ),
            color=discord.Color.dark_purple()
        )
        url = str(row.get("avatar_url", "")).strip()
        if url:
            e.set_thumbnail(url=url)
        e.set_footer(text="Tout se met à jour ici. 🐾")
        return e

    @ui.button(label="🎭 Choisir mon Avatar", style=discord.ButtonStyle.primary)
    async def btn_avatar(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntAvatarView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🛒 Shop", style=discord.ButtonStyle.secondary)
    async def btn_shop(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntShopView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🎒 Inventory", style=discord.ButtonStyle.secondary)
    async def btn_inv(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntInventoryView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🤝 Chercher un allié (hebdo)", style=discord.ButtonStyle.primary)
    async def btn_ally(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        avatar_tag = str(player.get("avatar_tag", "")).strip().upper()
        if not avatar_tag:
            return await interaction.followup.send(catify("😾 Choisis d’abord ton avatar."), ephemeral=True)

        week_key = hs.hunt_week_key()  # utilise TON week_key (ISO ou Friday17). Idéal: unifier plus tard.
        roll_wk = hs.ally_roll_week_key_get(player)

        ally_tag, ally_url = hs.player_get_ally(player)
        if ally_tag:
            return await interaction.followup.send(catify(f"😼 Tu as déjà un allié: **{ally_tag}**."), ephemeral=True)

        if roll_wk == week_key:
            return await interaction.followup.send(catify("😾 Tu as déjà tenté de recruter un allié cette semaine."), ephemeral=True)

        # --- chances ---
        is_emp = str(player.get("is_employee", "0")).strip().lower() in ("1", "true", "yes")
        chance = 0.50 if is_emp else 0.10  # non employés: rare
        ok = (random.random() < chance)

        # on marque la tentative quoi qu'il arrive (anti-spam hebdo)
        hs.ally_roll_week_key_set_with_row(self.sheets, int(p_row_i), player, week_key)

        if not ok:
            hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip,
                   kind="ally_roll", message="ally roll fail",
                   meta={"week_key": week_key, "chance": chance})
            # refresh hub UI
            try:
                await interaction.message.edit(embed=self.build_embed(), view=self)
            except Exception:
                pass
            return await interaction.followup.send(catify("😾 Personne n’a répondu à l’appel cette semaine."), ephemeral=True)

        # pick ally among direction, excluding player's avatar
        tags = [t for t in hda.list_avatar_tags() if t != avatar_tag]
        if not tags:
            return await interaction.followup.send(catify("😾 Impossible de choisir un allié."), ephemeral=True)

        picked = random.choice(tags)
        img = hda.get_avatar_image(picked)

        hs.player_set_ally(self.sheets, int(p_row_i), picked, img)
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip,
               kind="ally_roll", message=f"ally recruited {picked}",
               meta={"week_key": week_key, "chance": chance, "picked": picked})

        # annonce publique (salon)
        try:
            await interaction.channel.send(f"📣 <@{self.discord_id}> a recruté un allié : **[{picked}]**")
        except Exception:
            pass

        # refresh hub UI
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Un allié répond à l’appel: **{picked}**."), ephemeral=True)

    @ui.button(label="🤝 Mon allié", style=discord.ButtonStyle.primary)
    async def btn_ally(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntAllyView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="🏆 Weekly", style=discord.ButtonStyle.secondary)
    async def btn_weekly(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntWeeklyView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    
    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for it in self.children:
            it.disabled = True
        await _edit(interaction, content="✅ HUNT fermé.", embed=None, view=self)

# ==========================================================
# AVATAR (Select + Confirm + annonce publique)
# ==========================================================
# hunt_ui.py (extrait)

class AvatarSelect(ui.Select):
    def __init__(self, view: "HuntAvatarView"):
        options = []
        for a in AVATARS:
            options.append(discord.SelectOption(
                label=a.name,
                value=a.tag,
                description=a.short[:100],
            ))
        super().__init__(placeholder="Choisis ton avatar…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_tag = (self.values[0] or "").strip().upper()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class AvatarConfirmButton(ui.Button):
    def __init__(self, view: "HuntAvatarView"):
        super().__init__(label="✅ Confirmer", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        tag = (self.v.selected_tag or "").strip().upper()
        if not tag:
            return await interaction.response.send_message("😾 Choisis d’abord un avatar.", ephemeral=True)

        # ACK rapide
        await interaction.response.defer(ephemeral=True)

        # --- 1) write Sheets (avatar_tag + avatar_url) ---
        a = get_avatar(tag)
        avatar_url = a.image if a else ""

        # si ton view a player_row_i et services:
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "avatar_tag", tag)
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "avatar_url", avatar_url)
        self.v.s.update_cell_by_header("HUNT_PLAYERS", self.v.player_row_i, "updated_at", now_iso())

        # --- 2) annonce publique ---
        title = format_player_title(self.v.pseudo, tag)
        try:
            await interaction.channel.send(f"📣 **{title}** a choisi son avatar : **[{tag}]**")
        except Exception:
            pass

        # --- 3) lock UI + refresh embed ---
        self.v.confirmed = True
        for item in self.v.children:
            item.disabled = True

        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(f"✅ Avatar confirmé : **[{tag}]**", ephemeral=True)


class HuntAvatarView(ui.View):
    def __init__(self, *, parent: "HuntHubView"):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo
        self.selected_tag: Optional[str] = None
        self.confirmed = False

        self.add_item(AvatarSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # empêche un autre joueur de cliquer
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre /hunt."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player or {}

        current = str(row.get("avatar_tag", "")).strip().upper() or "?"
        pick = (self.selected_tag or current).strip().upper()

        e = discord.Embed(
            title="🎭 Choix d’Avatar",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"Actuel: **[{current}]**\n"
                f"Sélection: **[{pick}]**\n\n"
                "Choisis dans la liste, puis confirme."
            ),
            color=discord.Color.blurple()
        )

        # image du perso sélectionné (ou actuel)
        img = avatar_image_url(pick)
        if img:
            e.set_image(url=img)

        if self.confirmed:
            e.add_field(name="✅ Confirmé", value=f"Avatar défini sur **[{pick}]**", inline=False)
            e.set_footer(text="Mikasa note ça dans le registre. 🐾")
        else:
            e.set_footer(text="Tu confirmes = c’est gravé. 🐾")

        return e

    @ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success)
    async def btn_confirm(self, interaction: discord.Interaction, button: ui.Button):
        tag = (self.selected_tag or "").strip().upper()
        if not tag:
            return await interaction.response.send_message(catify("😾 Choisis un avatar d’abord."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # player row
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(
                self.sheets,
                discord_id=self.discord_id,
                vip_code=self.code_vip,
                pseudo=self.pseudo,
                is_employee=self.parent.is_employee
            )

        url = avatar_image_url(tag)

        # write Sheets (avatar_tag + avatar_url)
        hs.player_set_avatar(self.sheets, int(row_i), tag=tag, url=url)

        # annonce publique
        try:
            title = format_player_title(self.pseudo, tag)  # si tu utilises hunt_data.py
            await interaction.channel.send(f"📣 **{title}** a choisi son avatar : **[{tag}]**")
        except Exception:
            try:
                await interaction.channel.send(f"📣 <@{self.discord_id}> a choisi **[{tag}]** pour HUNT.")
            except Exception:
                pass

        # log
        hs.log(
            self.sheets,
            discord_id=self.discord_id,
            code_vip=self.code_vip,
            kind="avatar",
            message=f"avatar set {tag}",
            meta={"tag": tag, "url": url}
        )

        # lock UI
        self.confirmed = True
        for it in self.children:
            it.disabled = True

        # refresh message principal
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Avatar confirmé : **[{tag}]**"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

# -------------------------
# petites utilitaires
# -------------------------
def _money(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        n = 0
    return f"{n:,}".replace(",", " ")

def _power_lines(power: Dict[str, Any]) -> str:
    if not power:
        return "Aucun bonus."
    parts = []
    for k, v in power.items():
        parts.append(f"• {k}: **{v}**")
    return "\n".join(parts)

def _safe_str(x: Any) -> str:
    return str(x or "").strip()

def _edit(interaction: discord.Interaction, *, content: Optional[str] = None, embed=None, view=None):
    # ton helper existe déjà chez toi normalement
    return interaction.response.edit_message(content=content, embed=embed, view=view)


# ==========================================================
# SHOP
# ==========================================================
class HuntShopItemSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        options: List[discord.SelectOption] = []
        for item in view.items[:25]:
            iid = _safe_str(item.get("item_id"))
            name = _safe_str(item.get("name")) or iid
            price = hs.item_price(item)
            rarity = _safe_str(item.get("rarity"))
            typ = _safe_str(item.get("type"))
            label = f"{name}"
            desc = f"{typ} | {rarity} | {price}$"
            options.append(discord.SelectOption(label=label[:100], value=iid, description=desc[:100]))

        super().__init__(placeholder="Choisis un item à acheter…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.values[0] or "").strip()
        self.v.selected_item_id = iid
        self.v.mode = "preview"
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntShopView(ui.View):
    def __init__(self, *, parent):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.active_tab: str = "NORMAL"          # "NORMAL" / "BLACK"
        self.selected_item_id: Optional[str] = None

        self.tab_select = ShopTabSelect(self)
        self.item_select = ShopItemSelect(self)

        self.add_item(self.tab_select)
        self.add_item(self.item_select)

    def _reload(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        items = self.sheets.get_all_records(hs.T_ITEMS)
        return p_row_i, (player or {}), (items or [])

    def _filter_rows_for_tab(self, items: list[dict]) -> list[dict]:
        out = []
        for r in items:
            tp = str(r.get("type", "")).strip().upper()
            if self.active_tab == "BLACK":
                # marché noir = types préfixés BLACK_ (recommandé)
                if tp.startswith("BLACK_"):
                    out.append(r)
            else:
                # normal = tout sauf BLACK_
                if not tp.startswith("BLACK_"):
                    out.append(r)
        # tri simple: prix croissant puis rareté
        def keyf(r):
            try:
                price = int(r.get("price", 0) or 0)
            except Exception:
                price = 0
            rarity = str(r.get("rarity", "")).strip().upper()
            return (price, rarity)
        out.sort(key=keyf)
        return out

    def build_embed(self) -> discord.Embed:
        p_row_i, player, items = self._reload()
        dollars = hs.player_money_get(player)

        rows = self._filter_rows_for_tab(items)
        by_id = {str(r.get("item_id","")).strip(): r for r in rows}

        pick = by_id.get(self.selected_item_id or "", None)
        pick_name = str(pick.get("name")) if pick else "—"
        pick_price = str(pick.get("price","")) if pick else ""
        pick_desc = str(pick.get("description","")).strip() if pick else ""

        title = "🛒 Shop normal" if self.active_tab == "NORMAL" else "🕳️ Marché noir"
        e = discord.Embed(
            title=title,
            description=(
                f"👤 **{self.pseudo}**\n"
                f"💰 Argent: **{dollars}**$\n\n"
                f"🎯 Sélection: `{self.selected_item_id or '—'}`\n"
                f"🧾 **{pick_name}**" + (f" • **{pick_price}$**" if pick_price else "") + "\n"
                + (f"{pick_desc}\n" if pick_desc else "")
            ),
            color=discord.Color.dark_purple()
        )

        # pas d’images pour le marché noir (ton souhait)
        if self.active_tab == "NORMAL":
            url = str(pick.get("image_url","")).strip() if pick else ""
            if url:
                e.set_thumbnail(url=url)

        # mini listing
        preview = []
        for r in rows[:10]:
            iid = str(r.get("item_id","")).strip()
            nm = str(r.get("name", iid)).strip()
            pr = str(r.get("price","")).strip()
            preview.append(f"• `{iid}` **{nm}** — {pr}$")
        e.add_field(name="🧺 Articles", value=("\n".join(preview) if preview else "*Vide*"), inline=False)

        e.set_footer(text="Change d’onglet et achète sans relancer la commande. 🐾")
        return e

    async def refresh(self, interaction: discord.Interaction):
        _, _, items = self._reload()
        rows = self._filter_rows_for_tab(items)
        self.item_select.rebuild(rows)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="💸 Acheter", style=discord.ButtonStyle.success)
    async def btn_buy(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        p_row_i, player, items = self._reload()
        rows = self._filter_rows_for_tab(items)
        by_id = {str(r.get("item_id","")).strip(): r for r in rows}

        r = by_id.get(self.selected_item_id or "", None)
        if not r:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        iid = str(r.get("item_id","")).strip()
        price = int(r.get("price", 0) or 0)

        dollars = hs.player_money_get(player)
        if dollars < price:
            return await interaction.followup.send(catify("😾 Pas assez d’argent."), ephemeral=True)

        # débite + add inv
        hs.player_money_add(self.sheets, int(p_row_i), -price)
        inv = hs.inv_load(str(player.get("inventory_json","")))
        hs.inv_add(inv, iid, 1)
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Achat: **{r.get('name', iid)}** (+1)"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


class HuntShopBuyButton(ui.Button):
    def __init__(self, view: HuntShopView):
        super().__init__(label="✅ Acheter (x1)", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        item = hs.item_get(self.v.sheets, self.v.selected_item_id or "")
        if not item:
            return await interaction.followup.send(catify("😾 Item introuvable."), ephemeral=True)

        price = hs.item_price(item)
        iid = _safe_str(item.get("item_id"))
        name = _safe_str(item.get("name")) or iid

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.v.sheets,
                discord_id=self.v.discord_id,
                vip_code=self.v.code_vip,
                pseudo=self.v.pseudo,
                is_employee=self.v.parent.is_employee
            )

        money = hs.player_money_get(player)
        if money < price:
            return await interaction.followup.send(catify(f"😾 Pas assez d’argent. Il te manque **{_money(price - money)}$**."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        hs.inv_add(inv, iid, 1)

        new_money = money - price

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "hunt_dollars", str(int(new_money)))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="shop_buy",
               message=f"buy {iid} x1", meta={"item_id": iid, "price": price})

        # UI refresh: on repasse en liste
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Acheté: **{name}** (x1)"), ephemeral=True)


class HuntShopCancelButton(ui.Button):
    def __init__(self, view: HuntShopView):
        super().__init__(label="↩️ Retour liste", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntBackToHubButton(ui.Button):
    def __init__(self, parent: "HuntHubView"):
        super().__init__(label="🏠 Hub", style=discord.ButtonStyle.secondary)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

class HuntAllyView(ui.View):
    def __init__(self, *, parent):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

    def _reload_player(self):
        return hs.get_player_row(self.sheets, self.discord_id)

    def build_embed(self) -> discord.Embed:
        row_i, row = self._reload_player()
        row = row or {}
        avatar_tag = str(row.get("avatar_tag", "")).strip().upper() or "?"
        ally_tag = str(row.get("ally_tag", "")).strip().upper()
        ally_url = str(row.get("ally_url", "")).strip()

        week_key = hs.hunt_week_key()
        last_change = hs.ally_change_week_key_get(row)

        e = discord.Embed(
            title="🤝 Alliés (Direction)",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"🧍 Avatar: **{avatar_tag}**\n"
                f"📅 Semaine: `{week_key}`\n\n"
            ),
            color=discord.Color.dark_purple()
        )

        if ally_tag:
            e.add_field(name="Allié actuel", value=f"**[{ally_tag}]**", inline=False)
            if ally_url:
                e.set_thumbnail(url=ally_url)
            if last_change == week_key:
                e.add_field(name="Cooldown", value="Tu as déjà changé d’allié cette semaine.", inline=False)
            else:
                e.add_field(name="Cooldown", value="Tu peux changer d’allié **1x** cette semaine.", inline=False)
        else:
            e.add_field(name="Allié actuel", value="*Aucun*", inline=False)
            e.add_field(name="Règle", value="Un allié est permanent. Tu peux le changer **1x/semaine**.", inline=False)

        e.set_footer(text="Mikasa note les pactes. 🐾")
        return e

    @ui.button(label="🎲 Recruter / Changer (hebdo)", style=discord.ButtonStyle.success)
    async def btn_roll(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        p_row_i, player = self._reload_player()
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        avatar_tag = str(player.get("avatar_tag", "")).strip().upper()
        if not avatar_tag:
            return await interaction.followup.send(catify("😾 Choisis d’abord ton avatar."), ephemeral=True)

        week_key = hs.hunt_week_key()
        last_change = hs.ally_change_week_key_get(player)
        if last_change == week_key:
            return await interaction.followup.send(catify("😾 Tu as déjà changé d’allié cette semaine."), ephemeral=True)

        # Chances
        is_emp = str(player.get("is_employee", "0")).strip().lower() in ("1","true","yes")
        chance = 0.50 if is_emp else 0.10
        if random.random() >= chance:
            # on consomme quand même le “change” hebdo (anti-spam)
            hs.ally_change_week_key_set(self.sheets, int(p_row_i), player, week_key)
            try:
                await interaction.message.edit(embed=self.build_embed(), view=self)
            except Exception:
                pass
            return await interaction.followup.send(catify("😾 Personne n’a répondu à l’appel cette semaine."), ephemeral=True)

        # pick ally among direction excluding avatar
        candidates = [t for t in hd.list_avatar_tags() if t != avatar_tag]
        picked = random.choice(candidates)
        img = hda.get_avatar_image(picked)

        hs.player_set_ally(self.sheets, int(p_row_i), picked, img)
        hs.ally_change_week_key_set(self.sheets, int(p_row_i), player, week_key)
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        try:
            await interaction.channel.send(f"📣 <@{self.discord_id}> a lié un pacte avec **[{picked}]**.")
        except Exception:
            pass

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Nouvel allié: **[{picked}]**"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


# ==========================================================
# INVENTORY + EQUIP
# ==========================================================
class HuntInvOpenKeyButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="🔑 Ouvrir une clé", style=discord.ButtonStyle.primary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        # on passe en mode confirm (UI full)
        self.v.mode = "key_confirm"
        self.v._rebuild()
        await interaction.response.edit_message(embed=self.v.build_embed(), view=self.v)


class HuntKeyConfirmOpenButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="✅ Ouvrir maintenant", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # reload player
        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        n_keys = hs.inv_count(inv, "key")
        g_keys = hs.inv_count(inv, "gold_key")

        if n_keys <= 0 and g_keys <= 0:
            # retour list
            self.v.mode = "list"
            self.v._rebuild()
            try:
                await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
            except Exception:
                pass
            return await interaction.followup.send(catify("😾 Tu n’as aucune clé."), ephemeral=True)

        # choix: gold d’abord
        key_type = "gold_key" if g_keys > 0 else "key"

        # on consomme 1 clé
        ok = hs.inv_remove(inv, key_type, 1)
        if not ok:
            return await interaction.followup.send(catify("😾 Impossible de consommer la clé."), ephemeral=True)

        # loot (depuis HUNT_ITEMS)
        items = hs.items_all(self.v.sheets)
        res = hd.loot_open_key(items, key_type=key_type)

        item_id = str(res.get("item_id", "")).strip()
        item_name = str(res.get("item_name", "")).strip() or item_id
        qty = int(res.get("qty", 0) or 0)
        rarity = str(res.get("rarity", "")).strip()

        if item_id and qty > 0:
            hs.inv_add(inv, item_id, qty)

        # update player
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        # log HUNT_KEYS: on essaye de lier à une ligne "claim" non ouverte si elle existe.
        # sinon, on ne bloque pas: on loggue juste HUNT_LOG (le claim staff peut être décalé dans le temps).
        opened_at = now_iso()
        key_rows = hs.keys_find_unopened_for_player(self.v.sheets, discord_id=self.v.discord_id)

        if key_rows:
            key_row_i, key_row = key_rows[0]
            meta = {"opened_via": "inventory_ui", "key_type": key_type}
            try:
                hs.keys_log_open_result(
                    self.v.sheets,
                    key_row_i=key_row_i,
                    opened_at=opened_at,
                    item_id=item_id,
                    qty=qty,
                    rarity=rarity,
                    item_name=item_name,
                    meta=meta
                )
            except Exception:
                pass

        hs.log(
            self.v.sheets,
            discord_id=self.v.discord_id,
            code_vip=self.v.code_vip,
            kind="key_open",
            message=f"open {key_type} -> {item_id} x{qty} ({rarity})",
            meta={"key_type": key_type, "item_id": item_id, "qty": qty, "rarity": rarity}
        )

        # UI: on repasse en list + embed “résultat” en public dans le même message
        self.v.mode = "key_result"
        self.v.last_key_result = {"key_type": key_type, "item_id": item_id, "item_name": item_name, "qty": qty, "rarity": rarity}
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify("✅ Clé ouverte."), ephemeral=True)


class HuntKeyCancelOpenButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="↩️ Retour inventaire", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v._rebuild()
        await interaction.response.edit_message(embed=self.v.build_embed(), view=self.v)


class HuntInvItemSelect(ui.Select):
    def __init__(self, view: "HuntInventoryView"):
        options: List[discord.SelectOption] = []
        for iid, qty in view.inv_list[:25]:
            item = hs.item_get(view.sheets, iid) or {}
            name = _safe_str(item.get("name")) or iid
            typ = _safe_str(item.get("type")) or "item"
            rarity = _safe_str(item.get("rarity"))
            options.append(discord.SelectOption(
                label=f"{name} x{qty}"[:100],
                value=iid,
                description=f"{typ} | {rarity}"[:100]
            ))

        super().__init__(placeholder="Choisis un item…", options=options or [discord.SelectOption(label="(vide)", value="__empty__", description="")], min_values=1, max_values=1)
        self.v = view
        if not options:
            self.disabled = True

    async def callback(self, interaction: discord.Interaction):
        val = (self.values[0] or "").strip()
        if val == "__empty__":
            return await interaction.response.send_message(catify("😾 Inventaire vide."), ephemeral=True)
        self.v.selected_item_id = val
        self.v.mode = "preview"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntInvUseButton(ui.Button):
    def __init__(self, view: "HuntInventoryView"):
        super().__init__(label="🩹 Utiliser", style=discord.ButtonStyle.primary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.response.send_message(catify("😾 Item introuvable."), ephemeral=True)

        typ = hs.item_type(item)
        if typ != "consumable":
            return await interaction.response.send_message(catify("😾 Cet item ne peut pas être utilisé."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # reload player
        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu ne l’as plus."), ephemeral=True)

        # applique effet
        res = hd.consumable_apply(player, item)
        healed = int(res.get("healed", 0) or 0)
        msg = str(res.get("msg", "")).strip()

        # maj HP
        if healed > 0:
            hp = hs.player_hp_get(player)
            new_hp = max(0, hp + healed)
            hs.player_hp_set(self.v.sheets, int(p_row_i), new_hp)

        # consomme 1 item
        hs.inv_remove(inv, iid, 1)
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        name = _safe_str(item.get("name")) or iid
        hs.log(
            self.v.sheets,
            discord_id=self.v.discord_id,
            code_vip=self.v.code_vip,
            kind="use_item",
            message=f"use {iid}",
            meta={"item_id": iid, "healed": healed}
        )

        # refresh UI
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"🩹 **{name}** utilisé. {msg}"), ephemeral=True)

class HuntInventoryView(ui.View):
    def __init__(self, *, parent):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo
        self.selected_item_id: Optional[str] = None

        self.add_item(HuntInvSelect(self))

    def _reload(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        items = self.sheets.get_all_records(hs.T_ITEMS)
        items_by_id = {str(r.get("item_id","")).strip(): r for r in items}
        return p_row_i, (player or {}), items_by_id

    def build_embed(self) -> discord.Embed:
        p_row_i, player, items_by_id = self._reload()
        inv = hs.inv_load(str(player.get("inventory_json","")))

        ally_tag = str(player.get("ally_tag","")).strip().upper()
        ewp = hs.equip_get(player, who="player", slot="weapon")
        eap = hs.equip_get(player, who="player", slot="armor")
        ewa = hs.equip_get(player, who="ally", slot="weapon")
        eaa = hs.equip_get(player, who="ally", slot="armor")
        esp = hs.equip_get(player, who="player", slot="stim")
        esa = hs.equip_get(player, who="ally", slot="stim")

        def item_name(iid: str) -> str:
            if not iid:
                return "—"
            r = items_by_id.get(iid)
            return str(r.get("name", iid)) if r else iid

        lines = []
        # on liste seulement ce que tu as
        for iid, qty in hs.inv_iter(inv):  # si tu n'as pas inv_iter => je te le fournis
            if qty <= 0:
                continue
            r = items_by_id.get(iid, {})
            nm = str(r.get("name", iid))
            tp = str(r.get("type","")).upper()
            lines.append(f"• `{iid}` **{nm}** x{qty}  ({tp})")

        desc = (
            f"👤 **{self.pseudo}**\n"
            f"🤝 Allié: **{ally_tag or 'Aucun'}**\n\n"
            f"🗡️ Joueur: **{item_name(ewp)}** | 🛡️ **{item_name(eap)}** | 💉 **{item_name(esp)}**\n"
            f"🗡️ Allié: **{item_name(ewa)}** | 🛡️ **{item_name(eaa)}** | 💉 **{item_name(esa)}**\n\n"
            f"🎯 Sélection: `{self.selected_item_id or '—'}`\n"
        )


        e = discord.Embed(
            title="🎒 Inventaire",
            description=desc,
            color=discord.Color.blurple()
        )
        e.add_field(name="Objets", value=("\n".join(lines) if lines else "*Vide*"), inline=False)
        e.set_footer(text="Equipe ton joueur ou ton allié. 🐾")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _selected_item_row(self, items_by_id: Dict[str, dict]) -> Optional[dict]:
        if not self.selected_item_id:
            return None
        return items_by_id.get(self.selected_item_id)

    @ui.button(label="🗡️ Equiper Joueur", style=discord.ButtonStyle.success)
    async def btn_equip_player(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        p_row_i, player, items_by_id = self._reload()
        r = self._selected_item_row(items_by_id)
        if not r:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        iid = str(r.get("item_id","")).strip()
        tp = str(r.get("type","")).upper()

        if "STIM" in tp:
            slot = "stim"
        elif "WEAPON" in tp:
            slot = "weapon"
        elif "ARMOR" in tp:
            slot = "armor"
        else:
            slot = ""

        if not slot:
            return await interaction.followup.send(catify("😾 Cet item n’est pas équipable."), ephemeral=True)


        inv = hs.inv_load(str(player.get("inventory_json","")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu n’as pas cet item."), ephemeral=True)

        hs.equip_set(self.sheets, int(p_row_i), player, who="player", slot=slot, item_id=iid)

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass
        await interaction.followup.send(catify(f"✅ Equipé sur **joueur** ({slot})."), ephemeral=True)

    @ui.button(label="🤝 Equiper Allié", style=discord.ButtonStyle.primary)
    async def btn_equip_ally(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        p_row_i, player, items_by_id = self._reload()

        ally_tag = str(player.get("ally_tag","")).strip().upper()
        if not ally_tag:
            return await interaction.followup.send(catify("😾 Tu n’as pas d’allié."), ephemeral=True)

        r = self._selected_item_row(items_by_id)
        if not r:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        iid = str(r.get("item_id","")).strip()
        tp = str(r.get("type","")).upper()

        if "STIM" in tp:
            slot = "stim"
        elif "WEAPON" in tp:
            slot = "weapon"
        elif "ARMOR" in tp:
            slot = "armor"
        else:
            slot = ""

        if not slot:
            return await interaction.followup.send(catify("😾 Cet item n’est pas équipable."), ephemeral=True)


        inv = hs.inv_load(str(player.get("inventory_json","")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu n’as pas cet item."), ephemeral=True)

        hs.equip_set(self.sheets, int(p_row_i), player, who="ally", slot=slot, item_id=iid)

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass
        await interaction.followup.send(catify(f"✅ Equipé sur **allié** ({slot})."), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


class HuntInvSelect(ui.Select):
    def __init__(self, view: HuntInventoryView):
        # options rebuilt at runtime in callback (simple: keep placeholder options, update on refresh isn't necessary)
        super().__init__(placeholder="Choisir un item...", min_values=1, max_values=1, options=[
            discord.SelectOption(label="(Ouvrir inventaire)", value="__noop__")
        ])
        self.inv_view = view

    async def callback(self, interaction: discord.Interaction):
        # rebuild options each time user clicks (Discord limitation friendly)
        p_row_i, player, items_by_id = self.inv_view._reload()
        inv = hs.inv_load(str(player.get("inventory_json","")))

        opts = []
        for iid, qty in hs.inv_iter(inv):
            if qty <= 0:
                continue
            r = items_by_id.get(iid, {})
            nm = str(r.get("name", iid))
            tp = str(r.get("type","")).upper()
            opts.append(discord.SelectOption(label=f"{nm} x{qty}", value=iid, description=tp[:90]))

        if not opts:
            return await interaction.response.send_message(catify("😾 Inventaire vide."), ephemeral=True)

        self.options = opts[:25]
        self.inv_view.selected_item_id = self.values[0] if self.values else None
        await self.inv_view.refresh(interaction)


class HuntInvBackButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="↩️ Retour inventaire", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntInvEquipButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="🧷 Équiper", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.response.send_message(catify("😾 Item introuvable."), ephemeral=True)
        
        typ = hs.item_type(item)
        if typ not in ("weapon", "armor"):
            return await interaction.response.send_message(catify("😾 Cet item ne peut pas être équipé."), ephemeral=True)

        self.v.mode = "equip_confirm"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntEquipConfirmButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="✅ Confirmer l’équipement", style=discord.ButtonStyle.success)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid)
        if not item:
            return await interaction.followup.send(catify("😾 Item introuvable."), ephemeral=True)

        typ = hs.item_type(item)
        if typ not in ("weapon", "armor"):
            return await interaction.followup.send(catify("😾 Cet item ne peut pas être équipé."), ephemeral=True)

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.v.sheets,
                discord_id=self.v.discord_id,
                vip_code=self.v.code_vip,
                pseudo=self.v.pseudo,
                is_employee=self.v.parent.is_employee
            )

        inv = hs.inv_load(str(player.get("inventory_json", "")))
        if hs.inv_count(inv, iid) <= 0:
            return await interaction.followup.send(catify("😾 Tu ne l’as plus dans ton inventaire."), ephemeral=True)

        equip = hs.equip_load(str(player.get("equipped_json", "")))
        ally = str(player.get("ally_tag", "")).strip()
        # choix slot
        if ally:
        # priorité joueur, plus tard tu ajouteras un bouton switch
            slot = "player_weapon" if typ == "weapon" else "player_armor"
        else:
            slot = "player_weapon" if typ == "weapon" else "player_armor"

        equip = hs.equip_set_slot(equip, slot, iid)

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "equipped_json", hs.equip_dump(equip))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        name = _safe_str(item.get("name")) or iid
        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="equip",
               message=f"equip {slot}={iid}", meta={"slot": slot, "item_id": iid})

        # refresh UI -> retour inventaire
        self.v.mode = "list"
        self.v.selected_item_id = None
        self.v._rebuild()
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Équipé: **{name}** → `{slot}`"), ephemeral=True)


class HuntEquipCancelButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="↩️ Annuler", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.mode = "preview"
        self.v._rebuild()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntInvUnequipButton(ui.Button):
    def __init__(self, view: HuntInventoryView):
        super().__init__(label="🧺 Déséquiper slot", style=discord.ButtonStyle.secondary)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        # déséquipe selon le type de l’item preview
        iid = (self.v.selected_item_id or "").strip()
        item = hs.item_get(self.v.sheets, iid) or {}
        typ = hs.item_type(item)

        if typ not in ("weapon", "armor"):
            return await interaction.response.send_message(catify("😾 Je ne sais pas quel slot déséquiper pour ça."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        p_row_i, player = hs.get_player_row(self.v.sheets, self.v.discord_id)
        if not p_row_i or not player:
            return await interaction.followup.send(catify("😾 Profil introuvable."), ephemeral=True)

        equip = hs.equip_load(str(player.get("equipped_json", "")))
        slot = "player_weapon" if typ == "weapon" else "player_armor"
        equip = hs.equip_set_slot(equip, slot, "")

        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "equipped_json", hs.equip_dump(equip))
        self.v.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        hs.log(self.v.sheets, discord_id=self.v.discord_id, code_vip=self.v.code_vip, kind="unequip",
               message=f"unequip {slot}", meta={"slot": slot})

        # refresh preview embed (reste sur preview)
        try:
            await interaction.message.edit(embed=self.v.build_embed(), view=self.v)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Slot vidé: `{slot}`"), ephemeral=True)


# ==========================================================
# SHOP
# ==========================================================
class ShopSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        self.v = view
        options = self.v._shop_options()
        super().__init__(placeholder="Choisir un item à acheter…", options=options[:25], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_item_id = self.values[0]
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntShopView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.selected_item_id: Optional[str] = None
        self.add_item(ShopSelect(self))

    def _items_for_sale(self) -> List[Dict[str, Any]]:
        items = hs.items_all(self.sheets)
        sale = []
        for it in items:
            try:
                price = int(it.get("price", 0) or 0)
            except Exception:
                price = 0
            if price > 0:
                sale.append(it)
        sale.sort(key=lambda it: (rarity_rank(str(it.get("rarity","common"))), hs.item_price(it), str(it.get("name",""))))
        return sale

    def _shop_options(self) -> List[discord.SelectOption]:
        opts = []
        for it in self._items_for_sale():
            iid = str(it.get("item_id","")).strip()
            name = str(it.get("name", iid)).strip()
            rarity = _rarity_label(str(it.get("rarity","common")))
            price = hs.item_price(it)
            opts.append(discord.SelectOption(
                label=f"{name} ({price}💵)",
                value=iid,
                description=f"{rarity} • {str(it.get('type','')).strip()}"
            ))
        if not opts:
            opts = [discord.SelectOption(label="(Shop vide)", value="__none__", description="Ajoute des items dans HUNT_ITEMS")]
        return opts

    def build_embed(self) -> discord.Embed:
        # refresh money/player
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player
        dollars = hs.player_money_get(row)

        e = discord.Embed(
            title="🛒 HUNT Shop",
            description=(
                f"👤 **{self.pseudo}** | 💰 **{_money(dollars)}**\n\n"
                "Sélectionne un item pour voir le détail, puis achète."
            ),
            color=discord.Color.dark_purple()
        )

        if self.selected_item_id and self.selected_item_id != "__none__":
            it = hs.item_by_id(self.sheets, self.selected_item_id)
            if it:
                price = hs.item_price(it)
                rarity = _rarity_label(str(it.get("rarity","common")))
                desc = str(it.get("description","")).strip() or "*Aucune description*"
                e.add_field(
                    name=f"📦 {it.get('name', self.selected_item_id)}",
                    value=f"Type: `{it.get('type','')}`\nRareté: **{rarity}**\nPrix: **{price}💵**\n\n{desc}",
                    inline=False
                )
                img = str(it.get("image_url","")).strip()
                if img:
                    e.set_thumbnail(url=img)

        e.set_footer(text="Achats instantanés. Inventaire mis à jour en direct. 🐾")
        return e

    async def _buy(self, interaction: discord.Interaction, qty: int):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne un item."), ephemeral=True)
        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it:
            return await interaction.response.send_message(catify("❌ Item introuvable."), ephemeral=True)

        price = hs.item_price(it)
        if price <= 0:
            return await interaction.response.send_message(catify("😾 Cet item n’est pas achetable."), ephemeral=True)

        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(self.sheets, discord_id=self.discord_id, vip_code=self.code_vip, pseudo=self.pseudo, is_employee=self.parent.is_employee)

        dollars = hs.player_money_get(row)
        total_cost = price * int(qty)
        if dollars < total_cost:
            return await interaction.response.send_message(catify(f"😾 Pas assez d’argent. Il te manque **{total_cost - dollars}💵**."), ephemeral=True)

        inv = hs.player_inv_get(row)
        hs.inv_add(inv, str(it.get("item_id","")).strip(), int(qty))
        hs.player_inv_set(self.sheets, int(row_i), inv)
        hs.player_money_set(self.sheets, int(row_i), dollars - total_cost)

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="shop_buy",
               message=f"buy {it.get('item_id')} x{qty}", meta={"qty": qty, "cost": total_cost})

        await interaction.response.send_message(catify(f"✅ Acheté **{it.get('name')}** x{qty} pour **{total_cost}💵**."), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🧾 Acheter x1", style=discord.ButtonStyle.success)
    async def btn_buy1(self, interaction: discord.Interaction, button: ui.Button):
        await self._buy(interaction, 1)

    @ui.button(label="🧾 Acheter x5", style=discord.ButtonStyle.success)
    async def btn_buy5(self, interaction: discord.Interaction, button: ui.Button):
        await self._buy(interaction, 5)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

# ==========================================================
# INVENTORY + EQUIP + KEY OPEN
# ==========================================================
class InvSelect(ui.Select):
    def __init__(self, view: "HuntInventoryView"):
        self.v = view
        options = self.v._inv_options()
        super().__init__(placeholder="Choisir un item…", options=options[:25], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_item_id = self.values[0]
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)

class HuntInventoryView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.selected_item_id: Optional[str] = None
        self.equip_target = "player"  # "player" or "ally"

        self.add_item(InvSelect(self))

    def _player_row(self) -> Tuple[int, Dict[str, Any]]:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(self.sheets, discord_id=self.discord_id, vip_code=self.code_vip, pseudo=self.pseudo, is_employee=self.parent.is_employee)
        return int(row_i), row

    def _inv_options(self) -> List[discord.SelectOption]:
        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        opts = []
        # tri par name si possible
        for iid, qty in sorted(inv.items(), key=lambda kv: kv[0]):
            it = hs.item_by_id(self.sheets, iid)
            name = (str(it.get("name","")).strip() if it else iid)
            rarity = _rarity_label(str(it.get("rarity","common")) if it else "common")
            typ = str(it.get("type","")).strip() if it else ""
            opts.append(discord.SelectOption(
                label=f"{name} x{qty}",
                value=iid,
                description=f"{rarity} • {typ}" if typ else rarity
            ))
        if not opts:
            opts = [discord.SelectOption(label="(Inventaire vide)", value="__none__", description="Va au shop")]
        return opts

    def _equipped_text(self, row: Dict[str, Any]) -> str:
        eq = hs.player_eq_get(row)
        pw = eq.get("player_weapon") or "-"
        pa = eq.get("player_armor") or "-"
        aw = eq.get("ally_weapon") or "-"
        aa = eq.get("ally_armor") or "-"
        ally_tag = str(row.get("ally_tag","")).strip()
        return (
            f"🧍 Player: weapon **{pw}**, armor **{pa}**\n"
            + (f"🤝 Ally ({ally_tag}): weapon **{aw}**, armor **{aa}**\n" if ally_tag else "🤝 Ally: *(aucun)*\n")
        )

    def build_embed(self) -> discord.Embed:
        row_i, row = self._player_row()
        dollars = hs.player_money_get(row)

        e = discord.Embed(
            title="🎒 Inventory",
            description=(
                f"👤 **{self.pseudo}** | 💰 **{_money(dollars)}**\n\n"
                + self._equipped_text(row)
                + f"\n🎯 Cible equip: **{self.equip_target.upper()}**"
            ),
            color=discord.Color.blurple()
        )

        if self.selected_item_id and self.selected_item_id not in ("__none__", ""):
            it = hs.item_by_id(self.sheets, self.selected_item_id)
            inv = hs.player_inv_get(row)
            qty = hs.inv_count(inv, self.selected_item_id)
            if it:
                rarity = _rarity_label(str(it.get("rarity","common")))
                desc = str(it.get("description","")).strip() or "*Aucune description*"
                e.add_field(
                    name=f"📦 {it.get('name', self.selected_item_id)} x{qty}",
                    value=f"Type: `{it.get('type','')}`\nRareté: **{rarity}**\n\n{desc}",
                    inline=False
                )
                img = str(it.get("image_url","")).strip()
                if img:
                    e.set_thumbnail(url=img)
            else:
                e.add_field(name=f"📦 {self.selected_item_id} x{qty}", value="(item non trouvé dans HUNT_ITEMS)", inline=False)

        e.set_footer(text="Equip/Key open se fait ici. 🐾")
        return e

    def _set_buttons_state(self):
        # Active/désactive boutons selon sélection
        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        it = hs.item_by_id(self.sheets, self.selected_item_id or "")
        qty = hs.inv_count(inv, self.selected_item_id or "")

        can_equip = bool(it and qty > 0 and hd.is_equippable(it))
        is_key = bool(it and qty > 0 and str(it.get("type","")).strip().lower() in ("key", "gold_key"))
        ally_exists = bool(str(row.get("ally_tag","")).strip())

        for child in self.children:
            if isinstance(child, ui.Button) and child.custom_id:
                if child.custom_id == "inv_equip":
                    child.disabled = not can_equip
                if child.custom_id == "inv_openkey":
                    child.disabled = not is_key
                if child.custom_id == "inv_target":
                    child.disabled = not ally_exists

    async def _refresh(self, interaction: discord.Interaction):
        # rebuild select options
        self.clear_items()
        self.add_item(InvSelect(self))
        # re-add buttons (they are declared as decorators, Discord keeps them; but after clear_items we must re-add)
        # -> easiest: re-add by iterating original children? not possible after clear. So we avoid clear for buttons.
        # Instead: do NOT clear buttons; only replace the select by removing it first.
        # We'll do a safer approach: don't clear_items here.
        pass

    @ui.button(label="🎯 Cible: Player/Ally", style=discord.ButtonStyle.secondary, custom_id="inv_target")
    async def btn_target(self, interaction: discord.Interaction, button: ui.Button):
        row_i, row = self._player_row()
        if not str(row.get("ally_tag","")).strip():
            return await interaction.response.send_message(catify("😾 Tu n’as pas d’allié."), ephemeral=True)
        self.equip_target = "ally" if self.equip_target == "player" else "player"
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🗡️ Equip", style=discord.ButtonStyle.success, custom_id="inv_equip")
    async def btn_equip(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne un item."), ephemeral=True)

        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        if hs.inv_count(inv, self.selected_item_id) <= 0:
            return await interaction.response.send_message(catify("😾 Tu n’en as pas."), ephemeral=True)

        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it or not hd.is_equippable(it):
            return await interaction.response.send_message(catify("😾 Cet item n’est pas équipable."), ephemeral=True)

        slot = hd.equip_slot(it)
        if not slot:
            return await interaction.response.send_message(catify("😾 Slot inconnu."), ephemeral=True)

        eq = hs.player_eq_get(row)
        name = str(it.get("name", self.selected_item_id)).strip()

        if self.equip_target == "player":
            if slot == "weapon":
                eq["player_weapon"] = name
                eq["player_weapon_id"] = self.selected_item_id
            else:
                eq["player_armor"] = name
                eq["player_armor_id"] = self.selected_item_id
        else:
            if slot == "weapon":
                eq["ally_weapon"] = name
                eq["ally_weapon_id"] = self.selected_item_id
            else:
                eq["ally_armor"] = name
                eq["ally_armor_id"] = self.selected_item_id

        hs.player_eq_set(self.sheets, row_i, eq)
        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="equip",
               message=f"equip {self.equip_target} {slot} {self.selected_item_id}", meta={"target": self.equip_target, "slot": slot})

        await interaction.response.send_message(catify(f"✅ Equip **{name}** sur **{self.equip_target.upper()}**."), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="🔑 Open Key", style=discord.ButtonStyle.primary, custom_id="inv_openkey")
    async def btn_open_key(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_item_id or self.selected_item_id in ("__none__", ""):
            return await interaction.response.send_message(catify("😾 Sélectionne une clé."), ephemeral=True)

        row_i, row = self._player_row()
        inv = hs.player_inv_get(row)
        if hs.inv_count(inv, self.selected_item_id) <= 0:
            return await interaction.response.send_message(catify("😾 Tu n’en as pas."), ephemeral=True)

        it = hs.item_by_id(self.sheets, self.selected_item_id)
        if not it:
            return await interaction.response.send_message(catify("❌ Item clé introuvable."), ephemeral=True)

        key_type = str(it.get("type","")).strip().lower()
        if key_type not in ("key", "gold_key"):
            return await interaction.response.send_message(catify("😾 Ce n’est pas une clé."), ephemeral=True)

        # consume key
        if not hs.inv_remove(inv, self.selected_item_id, 1):
            return await interaction.response.send_message(catify("😾 Impossible de consommer la clé."), ephemeral=True)

        # loot
        all_items = hs.items_all(self.sheets)
        loot_id, loot_qty, loot_rarity, loot_name = hd.loot_pick_from_items(all_items, key_type=key_type)

        if loot_id:
            hs.inv_add(inv, loot_id, loot_qty)

        hs.player_inv_set(self.sheets, row_i, inv)

        # update HUNT_KEYS row (si on en trouve une non ouverte)
        k_row_i, k_row = hs.find_unopened_key_row(self.sheets, self.discord_id, key_type=key_type)
        if k_row_i:
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "opened_at", now_iso())
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_item_id", loot_id)
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_qty", str(loot_qty))
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_rarity", loot_rarity)
            hs.sheets.update_cell_by_header("HUNT_KEYS", int(k_row_i), "open_item_name", loot_name)

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="key_open",
               message=f"open {key_type} -> {loot_id} x{loot_qty}", meta={"rarity": loot_rarity})

        await interaction.response.send_message(catify(f"🎁 Tu ouvres ta **{key_type}** → **{loot_name}** x{loot_qty} (**{_rarity_label(loot_rarity)}**)"), ephemeral=True)
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

class HuntWeeklyView(ui.View):
    def __init__(self, *, parent):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

    def build_embed(self) -> discord.Embed:
        week_key = hs.hunt_week_key()
        top = hs.weekly_top(self.sheets, week_key, limit=10)

        lines = []
        for i, r in enumerate(top, start=1):
            pseudo = str(r.get("pseudo","")).strip() or str(r.get("code_vip","")).strip() or "?"
            try:
                sc = int(r.get("score", 0) or 0)
            except Exception:
                sc = 0
            w = r.get("wins", 0)
            d = r.get("deaths", 0)
            b = r.get("boss_kills", 0)
            s = r.get("steals", 0)
            lines.append(f"**#{i}** {pseudo} — **{sc}** pts (W:{w} D:{d} B:{b} S:{s})")

        e = discord.Embed(
            title=f"🏆 Weekly Top — `{week_key}`",
            description=("\n".join(lines) if lines else "*Aucun score cette semaine.*"),
            color=discord.Color.gold()
        )
        e.set_footer(text="Le trophée observe en silence. 🐾")
        return e

    @ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def btn_refresh(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

class HuntShopView(ui.View):
    def __init__(self, *, parent):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.market = "SHOP"  # SHOP or BLACK
        self.selected_item_id: Optional[str] = None

        self.add_item(HuntShopMarketSelect(self))
        self.add_item(HuntShopItemSelect(self))

    def _reload(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        items = self.sheets.get_all_records(hs.T_ITEMS)
        return p_row_i, (player or {}), items

    def _is_black(self, item: dict) -> bool:
        tp = str(item.get("type","")).upper()
        return tp.startswith("BLACK_")

    def _market_items(self, items: list) -> list:
        if self.market == "BLACK":
            return [r for r in items if self._is_black(r)]
        return [r for r in items if not self._is_black(r)]

    def build_embed(self) -> discord.Embed:
        p_row_i, player, items = self._reload()
        dollars = int(player.get("hunt_dollars", 0) or 0)

        pool = self._market_items(items)
        by_id = {str(r.get("item_id","")).strip(): r for r in pool}
        picked = by_id.get(self.selected_item_id or "", None)

        title = "🛒 Shop" if self.market == "SHOP" else "🕶️ Marché Noir"
        e = discord.Embed(
            title=title,
            description=(
                f"👤 **{self.pseudo}**\n"
                f"💰 Argent: **{dollars}**\n"
                f"🎯 Sélection: `{self.selected_item_id or '—'}`\n"
            ),
            color=(discord.Color.blurple() if self.market == "SHOP" else discord.Color.dark_gray())
        )

        if picked:
            name = str(picked.get("name",""))
            desc = str(picked.get("description",""))
            rarity = str(picked.get("rarity",""))
            price = int(picked.get("price", 0) or 0)
            e.add_field(
                name=f"{name} — {price}$",
                value=f"Rareté: **{rarity}**\n{desc}",
                inline=False
            )

            # IMPORTANT: marché noir => PAS D’IMAGE
            if self.market != "BLACK":
                img = str(picked.get("image_url","")).strip()
                if img:
                    e.set_thumbnail(url=img)

        e.set_footer(text="Acheter ajoute dans ton inventaire. 🐾")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="🛍️ Acheter x1", style=discord.ButtonStyle.success)
    async def btn_buy(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        if not self.selected_item_id:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        p_row_i, player, items = self._reload()
        pool = self._market_items(items)
        by_id = {str(r.get("item_id","")).strip(): r for r in pool}
        picked = by_id.get(self.selected_item_id)
        if not picked:
            return await interaction.followup.send(catify("😾 Item introuvable."), ephemeral=True)

        price = int(picked.get("price", 0) or 0)
        dollars = int(player.get("hunt_dollars", 0) or 0)
        if dollars < price:
            return await interaction.followup.send(catify("😾 Pas assez d’argent."), ephemeral=True)

        iid = str(picked.get("item_id","")).strip()
        inv = hs.inv_load(str(player.get("inventory_json","")))
        hs.inv_add(inv, iid, 1)

        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "inventory_json", hs.inv_dump(inv))
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "hunt_dollars", str(dollars - price))
        self.sheets.update_cell_by_header(hs.T_PLAYERS, int(p_row_i), "updated_at", now_iso())

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Acheté: `{iid}` x1"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


class HuntShopMarketSelect(ui.Select):
    def __init__(self, view: HuntShopView):
        super().__init__(
            placeholder="Choisir marché…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Shop", value="SHOP"),
                discord.SelectOption(label="Marché Noir", value="BLACK"),
            ]
        )
        self.shop_view = view

    async def callback(self, interaction: discord.Interaction):
        self.shop_view.market = self.values[0]
        self.shop_view.selected_item_id = None
        await self.shop_view.refresh(interaction)


class HuntShopItemSelect(ui.Select):
    def __init__(self, view: HuntShopView):
        super().__init__(placeholder="Choisir un item…", min_values=1, max_values=1, options=[
            discord.SelectOption(label="(ouvre la liste)", value="__noop__")
        ])
        self.shop_view = view

    async def callback(self, interaction: discord.Interaction):
        p_row_i, player, items = self.shop_view._reload()
        pool = self.shop_view._market_items(items)

        opts = []
        for r in pool:
            iid = str(r.get("item_id","")).strip()
            nm = str(r.get("name","")).strip() or iid
            price = int(r.get("price", 0) or 0)
            tp = str(r.get("type","")).upper()
            opts.append(discord.SelectOption(label=f"{nm} — {price}$", value=iid, description=tp[:90]))

        if not opts:
            return await interaction.response.send_message(catify("😾 Aucun item ici."), ephemeral=True)

        self.options = opts[:25]
        self.shop_view.selected_item_id = self.values[0]
        await self.shop_view.refresh(interaction)

    # NOTE: Discord ne rappelle pas automatiquement _set_buttons_state
    # Donc on le fait dans interaction_check via edit events? simple: on laisse OK,
    # car les boutons protègent aussi côté serveur (checks).
