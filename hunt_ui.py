# hunt_ui.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import discord
from discord import ui

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

    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.player
        dollars = hs.player_money_get(row)
        avatar_tag = str(row.get("avatar_tag", "")).strip() or "?"
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
        for a in AVATARS:
            options.append(discord.SelectOption(label=a["label"], value=a["tag"], description=f"Choisir {a['label']}"))
        super().__init__(placeholder="Choisis ton avatar…", options=options, min_values=1, max_values=1)
        self.v = view

    async def callback(self, interaction: discord.Interaction):
        self.v.selected_tag = self.values[0]
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

    def build_embed(self) -> discord.Embed:
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        row = row or self.parent.player
        current = str(row.get("avatar_tag", "")).strip() or "?"
        pick = self.selected_tag or current

        e = discord.Embed(
            title="🎭 Choix d’Avatar",
            description=(
                f"👤 **{self.pseudo}**\n"
                f"Actuel: **{current}**\n"
                f"Sélection: **{pick}**\n\n"
                "Choisis dans la liste, puis confirme."
            ),
            color=discord.Color.blurple()
        )
        img = avatar_image_url(pick)
        if img:
            e.set_image(url=img)

        if self.confirmed:
            e.add_field(name="✅ Confirmé", value=f"Avatar défini sur **{pick}**", inline=False)
            e.set_footer(text="Mikasa note ça dans le registre. 🐾")
        else:
            e.set_footer(text="Tu ne pourras pas dire que tu ne savais pas. 🐾")
        return e

    @ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success)
    async def btn_confirm(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_tag:
            return await interaction.response.send_message(catify("😾 Choisis un avatar d’abord."), ephemeral=True)

        # update sheets
        row_i, row = hs.get_player_row(self.sheets, self.discord_id)
        if not row_i or not row:
            row_i, row = hs.ensure_player(self.sheets, discord_id=self.discord_id, vip_code=self.code_vip, pseudo=self.pseudo, is_employee=self.parent.is_employee)

        tag = self.selected_tag.strip().upper()
        url = avatar_image_url(tag)
        hs.player_set_avatar(self.sheets, int(row_i), tag=tag, url=url)

        # annonce publique (dans le salon)
        try:
            await interaction.channel.send(f"📣 <@{self.discord_id}> a choisi **[{tag}]** pour HUNT.")
        except Exception:
            pass

        hs.log(self.sheets, discord_id=self.discord_id, code_vip=self.code_vip, kind="avatar", message=f"avatar set {tag}", meta={"tag": tag})

        self.confirmed = True
        for it in self.children:
            if isinstance(it, ui.Select):
                it.disabled = True
        button.disabled = True
        await _edit(interaction, embed=self.build_embed(), view=self)

    @ui.button(label="↩️ Retour", style=discord.ButtonStyle.secondary)
    async def btn_back(self, interaction: discord.Interaction, button: ui.Button):
        await _edit(interaction, embed=self.parent.build_embed(), view=self.parent)

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

    # NOTE: Discord ne rappelle pas automatiquement _set_buttons_state
    # Donc on le fait dans interaction_check via edit events? simple: on laisse OK,
    # car les boutons protègent aussi côté serveur (checks).
