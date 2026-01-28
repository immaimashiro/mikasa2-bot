# hunt_ui.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import discord
from discord import ui

import hunt_services as hs
import hunt_domain as hd
import hunt_data as hda

from services import catify, now_iso


# ==========================================================
# Helpers (unique, pas de doublons)
# ==========================================================

def _money(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return "0"

def format_player_title(player_name: str, avatar_tag: str) -> str:
    player_name = (player_name or "").strip() or "Joueur"
    avatar_tag = (avatar_tag or "").strip().upper()
    return player_name if not avatar_tag else f"{player_name} [{avatar_tag}]"

def _rarity_label(r: str) -> str:
    r = (r or "").strip().upper()
    return {
        "COMMON": "Common",
        "UNCOMMON": "Uncommon",
        "RARE": "Rare",
        "EPIC": "Epic",
        "LEGENDARY": "Legendary",
    }.get(r, r or "Common")

def rarity_rank(r: str) -> int:
    r = (r or "").strip().upper()
    return {
        "COMMON": 1,
        "UNCOMMON": 2,
        "RARE": 3,
        "EPIC": 4,
        "LEGENDARY": 5,
    }.get(r, 99)

async def _edit(interaction: discord.Interaction, *, content: Optional[str] = None, embed=None, view=None):
    try:
        if interaction.response.is_done():
            await interaction.message.edit(content=content, embed=embed, view=view)
        else:
            await interaction.response.edit_message(content=content, embed=embed, view=view)
    except Exception:
        pass

def _is_black_item(item: Dict[str, Any]) -> bool:
    """
    Marché noir:
    - type commence par BLACK_
    - OU item_id commence par bm_ / BM_
    """
    tp = str(item.get("type", "")).strip().upper()
    iid = str(item.get("item_id", "")).strip().upper()
    return tp.startswith("BLACK_") or iid.startswith("BM_")

def _slot_from_item_type(tp: str) -> str:
    tp = (tp or "").strip().upper()
    if "STIM" in tp:
        return "stim"
    if "WEAPON" in tp:
        return "weapon"
    if "ARMOR" in tp:
        return "armor"
    return ""


# ==========================================================
# HUB (message unique, tout se fait dessus)
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

        # Allié permanent: tentative silencieuse au chargement du hub
        try:
            changed = hd.try_assign_permanent_ally(self.sheets, int(self.p_row_i), dict(self.player or {}))
            if changed:
                _, self.player = hs.get_player_row(self.sheets, self.discord_id)
        except Exception:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre HUNT."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        _, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.player or {}

        dollars = hs.player_money_get(row)
        avatar_tag = str(row.get("avatar_tag", "")).strip().upper() or "?"
        avatar_url = str(row.get("avatar_url", "")).strip()

        ally_tag = str(row.get("ally_tag", "")).strip().upper()
        ally_url = str(row.get("ally_url", "")).strip()

        e = discord.Embed(
            title="🗺️ HUNT — Hub",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"🎴 VIP: `{self.code_vip}`\n"
                f"🧍 Avatar: **[{avatar_tag}]**\n"
                f"💰 Argent: **{_money(dollars)}💵**\n"
            ),
            color=discord.Color.dark_purple()
        )

        if avatar_url:
            e.set_thumbnail(url=avatar_url)

        if ally_tag:
            e.add_field(name="🤝 Allié", value=f"**[{ally_tag}]**", inline=True)
        else:
            e.add_field(name="🤝 Allié", value="*Aucun (pas de chance cette fois)*", inline=True)

        if ally_url and ally_tag:
            e.set_image(url=ally_url)

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

    @ui.button(label="🤝 Mon allié", style=discord.ButtonStyle.primary)
    async def btn_ally_view(self, interaction: discord.Interaction, button: ui.Button):
        view = HuntAllyView(parent=self)
        await _edit(interaction, embed=view.build_embed(), view=view)

    @ui.button(label="✅ Fermer", style=discord.ButtonStyle.success)
    async def btn_close(self, interaction: discord.Interaction, button: ui.Button):
        for it in self.children:
            it.disabled = True
        await _edit(interaction, content="✅ HUNT fermé.", embed=None, view=self)


# ==========================================================
# AVATAR (Select + Confirm + annonce publique)
# ==========================================================

class AvatarSelect(ui.Select):
    def __init__(self, view: "HuntAvatarView"):
        options = []
        for a in hda.AVATARS:
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


class HuntAvatarView(ui.View):
    def __init__(self, *, parent: HuntHubView):
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
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message(catify("😾 Pas touche. Lance ton propre /hunt."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        _, row = hs.get_player_row(self.sheets, self.discord_id)
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

        img = hda.get_avatar_image(pick)
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

        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(
                self.sheets,
                discord_id=self.discord_id,
                vip_code=self.code_vip,
                pseudo=self.pseudo,
                is_employee=self.parent.is_employee
            )

        url = hda.get_avatar_image(tag)
        hs.player_set_avatar(self.sheets, int(row_i), tag=tag, url=url)

        try:
            title = format_player_title(self.pseudo, tag)
            await interaction.channel.send(f"📣 **{title}** a choisi son avatar : **[{tag}]**")
        except Exception:
            pass

        hs.log(
            self.sheets,
            discord_id=self.discord_id,
            code_vip=self.code_vip,
            kind="avatar",
            message=f"avatar set {tag}",
            meta={"tag": tag, "url": url}
        )

        self.confirmed = True
        for it in self.children:
            it.disabled = True

        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Avatar confirmé : **[{tag}]**"), ephemeral=True)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


# ==========================================================
# ALLY VIEW (permanent)
# ==========================================================

class HuntAllyView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.pseudo = parent.pseudo

    def build_embed(self) -> discord.Embed:
        _, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or {}

        ally_tag = str(row.get("ally_tag", "")).strip().upper()
        ally_url = str(row.get("ally_url", "")).strip()

        e = discord.Embed(
            title="🤝 Ton allié",
            description=("Aucun allié pour le moment." if not ally_tag else f"Allié: **[{ally_tag}]**"),
            color=discord.Color.blurple()
        )
        if ally_url and ally_tag:
            e.set_image(url=ally_url)
        e.set_footer(text="Allié permanent. 🐾")
        return e

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)


# ==========================================================
# SHOP (2 onglets : NORMAL / BLACK)
# ==========================================================

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
        self.v._rebuild_item_select()
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class ShopItemSelect(ui.Select):
    def __init__(self, view: "HuntShopView"):
        self.v = view
        super().__init__(placeholder="Choisir un item…", options=[discord.SelectOption(label="(vide)", value="__none__")], min_values=1, max_values=1)

    def set_options(self, rows: List[Dict[str, Any]]):
        opts: List[discord.SelectOption] = []
        for r in rows[:25]:
            iid = str(r.get("item_id", "")).strip()
            if not iid:
                continue
            nm = str(r.get("name", iid)).strip()[:90]
            price = int(r.get("price", 0) or 0)
            rarity = _rarity_label(str(r.get("rarity", "")))
            tp = str(r.get("type", "")).strip().upper()

            desc = f"{rarity} • {price}$ • {tp}"
            opts.append(discord.SelectOption(label=nm, value=iid, description=desc[:100]))

        if not opts:
            opts = [discord.SelectOption(label="(vide)", value="__none__", description="Aucun item dispo.")]

        self.options = opts
        self.placeholder = "Choisir un item…"

    async def callback(self, interaction: discord.Interaction):
        iid = self.values[0]
        if iid == "__none__":
            return await interaction.response.defer(ephemeral=True)
        self.v.selected_item_id = iid
        await _edit(interaction, embed=self.v.build_embed(), view=self.v)


class HuntShopView(ui.View):
    def __init__(self, *, parent: HuntHubView):
        super().__init__(timeout=10 * 60)
        self.parent = parent
        self.sheets = parent.sheets
        self.discord_id = parent.discord_id
        self.code_vip = parent.code_vip
        self.pseudo = parent.pseudo

        self.active_tab: str = "NORMAL"  # NORMAL / BLACK
        self.selected_item_id: Optional[str] = None

        self.tab_select = ShopTabSelect(self)
        self.item_select = ShopItemSelect(self)
        self.add_item(self.tab_select)
        self.add_item(self.item_select)

        self._rebuild_item_select()

    def _reload(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.sheets,
                discord_id=self.discord_id,
                vip_code=self.code_vip,
                pseudo=self.pseudo,
                is_employee=self.parent.is_employee
            )
        items = self.sheets.get_all_records(hs.T_ITEMS)
        return int(p_row_i), (player or {}), (items or [])

    def _filter_rows(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for r in items:
            price = int(r.get("price", 0) or 0)
            if price <= 0:
                continue
            if self.active_tab == "BLACK":
                if _is_black_item(r):
                    out.append(r)
            else:
                if not _is_black_item(r):
                    out.append(r)

        out.sort(key=lambda r: (rarity_rank(str(r.get("rarity", ""))), int(r.get("price", 0) or 0), str(r.get("name", ""))))
        return out

    def _rebuild_item_select(self):
        _, _, items = self._reload()
        rows = self._filter_rows(items)
        self.item_select.set_options(rows)

    def build_embed(self) -> discord.Embed:
        _, player, items = self._reload()
        dollars = hs.player_money_get(player)

        rows = self._filter_rows(items)
        by_id = {str(r.get("item_id", "")).strip(): r for r in rows}
        pick = by_id.get(self.selected_item_id or "")

        title = "🛒 Shop normal" if self.active_tab == "NORMAL" else "🕳️ Marché noir"
        e = discord.Embed(
            title=title,
            description=(
                f"👤 **{self.pseudo}** | 💰 **{_money(dollars)}💵**\n\n"
                f"🎯 Sélection: `{self.selected_item_id or '—'}`\n"
                "Sélectionne un item puis achète."
            ),
            color=discord.Color.dark_purple()
        )

        if pick:
            name = str(pick.get("name", self.selected_item_id)).strip()
            rarity = _rarity_label(str(pick.get("rarity", "")))
            price = int(pick.get("price", 0) or 0)
            desc = str(pick.get("description", "")).strip() or "*Aucune description*"
            tp = str(pick.get("type", "")).strip()

            e.add_field(
                name=f"📦 {name}",
                value=f"Type: `{tp}`\nRareté: **{rarity}**\nPrix: **{price}💵**\n\n{desc}",
                inline=False
            )

            # IMPORTANT: PAS d'image pour le marché noir
            if self.active_tab == "NORMAL":
                img = str(pick.get("image_url", "")).strip()
                if img:
                    e.set_thumbnail(url=img)

        preview = []
        for r in rows[:10]:
            iid = str(r.get("item_id", "")).strip()
            nm = str(r.get("name", iid)).strip()
            pr = int(r.get("price", 0) or 0)
            preview.append(f"• `{iid}` **{nm}** — {pr}💵")
        e.add_field(name="🧺 Articles (aperçu)", value=("\n".join(preview) if preview else "*Vide*"), inline=False)

        e.set_footer(text="Achat = inventaire mis à jour direct. 🐾")
        return e

    async def _buy(self, interaction: discord.Interaction, qty: int):
        await interaction.response.defer(ephemeral=True)

        if not self.selected_item_id:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        p_row_i, player, items = self._reload()
        rows = self._filter_rows(items)
        by_id = {str(r.get("item_id", "")).strip(): r for r in rows}
        pick = by_id.get(self.selected_item_id)
        if not pick:
            return await interaction.followup.send(catify("😾 Item introuvable dans cet onglet."), ephemeral=True)

        price = int(pick.get("price", 0) or 0)
        total = price * int(qty)
        dollars = hs.player_money_get(player)
        if dollars < total:
            return await interaction.followup.send(catify(f"😾 Pas assez d’argent. Il te manque **{_money(total - dollars)}💵**."), ephemeral=True)

        inv = hs.player_inv_get(player)
        hs.inv_add(inv, str(pick.get("item_id", "")).strip(), int(qty))
        hs.player_inv_set(self.sheets, int(p_row_i), inv)
        hs.player_money_set(self.sheets, int(p_row_i), dollars - total)

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="shop_buy",
               message=f"buy {pick.get('item_id')} x{qty}", meta={"qty": qty, "cost": total, "tab": self.active_tab})

        # refresh UI
        self._rebuild_item_select()
        try:
            await interaction.message.edit(embed=self.build_embed(), view=self)
        except Exception:
            pass

        await interaction.followup.send(catify(f"✅ Acheté **{pick.get('name')}** x{qty} pour **{total}💵**."), ephemeral=True)

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
# INVENTORY (select + equip player/ally weapon/armor/stim)
# ==========================================================

class HuntInvSelect(ui.Select):
    def __init__(self, view: "HuntInventoryView"):
        self.v = view
        super().__init__(placeholder="Choisir un item…", options=[discord.SelectOption(label="(chargement)", value="__none__")], min_values=1, max_values=1)
        self._rebuild_options()

    def _rebuild_options(self):
        p_row_i, player, items_by_id = self.v._reload()
        inv = hs.inv_load(str(player.get("inventory_json", "")))

        opts: List[discord.SelectOption] = []
        for iid, qty in hs.inv_iter(inv):
            if qty <= 0:
                continue
            r = items_by_id.get(iid, {})
            nm = str(r.get("name", iid)).strip()
            tp = str(r.get("type", "")).strip().upper()
            opts.append(discord.SelectOption(label=f"{nm} x{qty}"[:100], value=iid, description=tp[:100]))

        if not opts:
            opts = [discord.SelectOption(label="(Inventaire vide)", value="__none__", description="Va au shop.")]

        self.options = opts[:25]
        self.placeholder = "Choisir un item…"

    async def callback(self, interaction: discord.Interaction):
        iid = self.values[0]
        if iid == "__none__":
            return await interaction.response.send_message(catify("😾 Inventaire vide."), ephemeral=True)
        self.v.selected_item_id = iid
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

        self.add_item(HuntInvSelect(self))

    def _reload(self):
        p_row_i, player = hs.get_player_row(self.sheets, self.discord_id)
        if not p_row_i or not player:
            p_row_i, player = hs.ensure_player(
                self.sheets,
                discord_id=self.discord_id,
                vip_code=self.code_vip,
                pseudo=self.pseudo,
                is_employee=self.parent.is_employee
            )
        items = self.sheets.get_all_records(hs.T_ITEMS)
        items_by_id = {str(r.get("item_id", "")).strip(): r for r in (items or [])}
        return int(p_row_i), (player or {}), items_by_id

    def build_embed(self) -> discord.Embed:
        _, player, items_by_id = self._reload()
        inv = hs.inv_load(str(player.get("inventory_json", "")))

        ally_tag = str(player.get("ally_tag", "")).strip().upper()

        ewp = hs.equip_get(player, who="player", slot="weapon")
        eap = hs.equip_get(player, who="player", slot="armor")
        esp = hs.equip_get(player, who="player", slot="stim")

        ewa = hs.equip_get(player, who="ally", slot="weapon")
        eaa = hs.equip_get(player, who="ally", slot="armor")
        esa = hs.equip_get(player, who="ally", slot="stim")

        def item_name(iid: str) -> str:
            iid = (iid or "").strip()
            if not iid:
                return "—"
            r = items_by_id.get(iid)
            return str(r.get("name", iid)) if r else iid

        lines = []
        for iid, qty in hs.inv_iter(inv):
            if qty <= 0:
                continue
            r = items_by_id.get(iid, {})
            nm = str(r.get("name", iid))
            tp = str(r.get("type", "")).upper()
            lines.append(f"• `{iid}` **{nm}** x{qty}  ({tp})")

        desc = (
            f"👤 **{self.pseudo}**\n"
            f"🤝 Allié: **{ally_tag or 'Aucun'}**\n\n"
            f"🗡️ Joueur: **{item_name(ewp)}** | 🛡️ **{item_name(eap)}** | 💉 **{item_name(esp)}**\n"
            f"🗡️ Allié: **{item_name(ewa)}** | 🛡️ **{item_name(eaa)}** | 💉 **{item_name(esa)}**\n\n"
            f"🎯 Sélection: `{self.selected_item_id or '—'}`\n"
        )

        e = discord.Embed(title="🎒 Inventaire", description=desc, color=discord.Color.blurple())
        e.add_field(name="Objets", value=("\n".join(lines) if lines else "*Vide*"), inline=False)
        e.set_footer(text="Equipe ton joueur ou ton allié. 🐾")
        return e

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

        iid = str(r.get("item_id", "")).strip()
        tp = str(r.get("type", "")).strip().upper()
        slot = _slot_from_item_type(tp)
        if not slot:
            return await interaction.followup.send(catify("😾 Cet item n’est pas équipable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
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

        ally_tag = str(player.get("ally_tag", "")).strip().upper()
        if not ally_tag:
            return await interaction.followup.send(catify("😾 Tu n’as pas d’allié."), ephemeral=True)

        r = self._selected_item_row(items_by_id)
        if not r:
            return await interaction.followup.send(catify("😾 Sélectionne un item."), ephemeral=True)

        iid = str(r.get("item_id", "")).strip()
        tp = str(r.get("type", "")).strip().upper()
        slot = _slot_from_item_type(tp)
        if not slot:
            return await interaction.followup.send(catify("😾 Cet item n’est pas équipable."), ephemeral=True)

        inv = hs.inv_load(str(player.get("inventory_json", "")))
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
