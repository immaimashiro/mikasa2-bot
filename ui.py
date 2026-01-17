# views discord.ui (Défis panel etc)

class DefiValidateView(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, tasks: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.tasks = tasks
        self.vip_pseudo = vip_pseudo

        # état initial depuis la sheet
        self.state = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }

        # IMPORTANT: tampon -> si un défi est déjà validé, on verrouille son bouton (pas de gomme)
        self.locked = {
            1: self.state[1],
            2: self.state[2],
            3: self.state[3],
            4: self.state[4],
        }

        self.message: discord.Message | None = None
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        lines = []
        for i in range(1, 5):
            lines.append(f"{yn_emoji(self.state[i])} {self.tasks[i-1]}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label}\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            + "\n".join(lines) +
            "\n\nClique pour cocher les ❌. Les ✔️ déjà tamponnés sont verrouillés."
        )

        embed = discord.Embed(
            title="📸 Validation des défis (HG)",
            description=desc,
            color=discord.Color.dark_purple()
        )
        embed.set_footer(text="Tampon Mikasa: une fois posé, il ne s’efface pas. 🐾")
        return embed

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("defi_toggle_"):
                n = int(child.custom_id.split("_")[-1])
                child.label = f"{yn_emoji(self.state[n])} Défi {n}"
                # verrou si déjà validé en sheet
                child.disabled = bool(self.locked[n])

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="❌ Défi 1", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_1")
    async def toggle_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[1] = not self.state[1]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 2", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_2")
    async def toggle_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[2] = not self.state[2]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 3", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_3")
    async def toggle_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[3] = not self.state[3]
        await self._edit(interaction)

    @discord.ui.button(label="❌ Défi 4", style=discord.ButtonStyle.secondary, custom_id="defi_toggle_4")
    async def toggle_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state[4] = not self.state[4]
        await self._edit(interaction)

    @discord.ui.button(label="✅ VALIDER", style=discord.ButtonStyle.success)
    async def commit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # sécurité anti-double clic
        await interaction.response.defer()

        # --- TON CODE ICI ---
        # ex:
        # enregistrer les défis cochés
        # update Google Sheet
        # envoyer confirmation

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(view=self)

        # ex: update sheet, calculs, etc.

        try:
            await interaction.edit_original_response(embed=final_embed, view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=final_embed, ephemeral=True)
            except Exception:
                pass

    
            # relire la ligne DEFIS pour éviter conflit
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return
    
        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
        updates = []

        for n in range(1, 5):
            if self.state.get(n) and not str(row2.get(f"d{n}", "")).strip():
                col = col_letter_for_defi(n)
                updates.append({
                    "range": f"{col}{row_i2}",
                    "values": [[stamp]]
                })


    
            if updates:
                ws_defis.batch_update(updates)
    
            # reload
            row_i3, row3 = get_defis_row(self.code, self.wk_key)
            done_after = defis_done_count(row3)
    
            awarded = False
    
            # points UNIQUEMENT au 1er défi de la semaine
            if done_before == 0 and done_after > 0:
                ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
                awarded = bool(ok1 and ok2)
    
            # si 4/4 -> completed + bonus + annonce (une seule fois)
            if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
                comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
                ws_defis.batch_update([
                    {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                    {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
                ])
    
                add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)
    
                if ANNOUNCE_CHANNEL_ID:
                    ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                    if ch:
                        await ch.send(catify(
                            f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                            f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                            chance=0.10
                        ))
    
            # verrouille tout et affiche résultat
            for item in self.children:
                item.disabled = True
    
            final_embed = self._build_embed()
            extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou aucune case nouvelle)."
            final_embed.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
            final_embed.set_footer(text="Tampon posé. Mikasa referme le carnet. 🐾")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass


class DefiWeek12View(discord.ui.View):
    def __init__(self, *, author: discord.Member, code: str, wk: int, wk_key: str, wk_label: str,
                 row_i: int, row: dict, choices: list[str], vip_pseudo: str):
        super().__init__(timeout=180)

        self.author = author
        self.code = code
        self.wk = wk
        self.wk_key = wk_key
        self.wk_label = wk_label
        self.row_i = row_i
        self.row = row
        self.choices = choices  # 12 textes
        self.vip_pseudo = vip_pseudo

        # d1..d4 déjà tamponnés ?
        self.state_slots = {
            1: bool(str(row.get("d1", "")).strip()),
            2: bool(str(row.get("d2", "")).strip()),
            3: bool(str(row.get("d3", "")).strip()),
            4: bool(str(row.get("d4", "")).strip()),
        }
        # verrou slots tamponnés
        self.locked_slots = {
            1: self.state_slots[1],
            2: self.state_slots[2],
            3: self.state_slots[3],
            4: self.state_slots[4],
        }

        # sélection en cours (jusqu’à 4) -> indices 0..11
        self.selected: set[int] = set()

        self.message: discord.Message | None = None

        # build 12 boutons dynamiques
        for i in range(12):
            self.add_item(Week12ChoiceButton(i))

        self.add_item(Week12ValidateButton())
        self._refresh_all()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                catify("😾 Pas touche. Lance ta propre commande `!defi CODE`."),
                ephemeral=True
            )
            return False
        return True

    def selected_count(self) -> int:
        return len(self.selected)

    def slots_done_count(self) -> int:
        return sum(1 for n in range(1, 5) if self.state_slots[n])

    def available_slots(self) -> int:
        return 4 - self.slots_done_count()

    def _build_embed(self) -> discord.Embed:
        wk_start, wk_end, _ = get_week_window()
        done = self.slots_done_count()
        lines = []
        for idx, txt in enumerate(self.choices):
            mark = "✔️" if idx in self.selected else "❌"
            lines.append(f"{mark} {txt}")

        desc = (
            f"👤 **{self.vip_pseudo}** • `{self.code}`\n"
            f"📌 {self.wk_label} (Freestyle)\n"
            f"🗓️ **{wk_start.strftime('%d/%m %H:%M')} → {wk_end.strftime('%d/%m %H:%M')}** (FR)\n\n"
            f"✅ Slots déjà validés: **{done}/4** (tampon)\n"
            f"🧩 Sélection en cours: **{self.selected_count()}/4** (max)\n\n"
            + "\n".join(lines)
            + "\n\nChoisis jusqu’à 4 défis, puis **VALIDER**."
        )

        embed = discord.Embed(
            title="🎭 Semaine 12 Freestyle (HG)",
            description=desc,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Freestyle: Mikasa compte exactement 4 preuves. 🐾")
        return embed

    def _refresh_all(self):
        # refresh labels + disabled selon sélection
        for item in self.children:
            if isinstance(item, Week12ChoiceButton):
                idx = item.idx
                item.label = f"{'✔️' if idx in self.selected else '❌'} {idx+1}"
                # si déjà 4 sélectionnées, on désactive les non-sélectionnées
                if self.selected_count() >= 4 and idx not in self.selected:
                    item.disabled = True
                else:
                    item.disabled = False

            if isinstance(item, Week12ValidateButton):
                item.disabled = (self.selected_count() == 0)

    async def _edit(self, interaction: discord.Interaction):
        self._refresh_all()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def commit_selected(self, interaction: discord.Interaction):
        # relire row
        row_i2, row2 = get_defis_row(self.code, self.wk_key)
        if not row_i2:
            await interaction.response.send_message(catify("❌ Ligne DEFIS introuvable. Relance `!defi CODE`."), ephemeral=True)
            return

        done_before = defis_done_count(row2)
        now_dt = now_fr()
        stamp = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # slots disponibles = cases vides d1..d4
        empty_slots = []
        for n in range(1, 5):
            if not str(row2.get(f"d{n}", "")).strip():
                empty_slots.append(n)

        # Tampon: on ne remplace jamais une case déjà remplie
        # On remplit les slots vides avec la sélection (jusqu’à 4)
        to_write = list(self.selected)[:len(empty_slots)]
        updates = []

        for k, choice_idx in enumerate(to_write):
            slot_n = empty_slots[k]
            col = col_letter_for_defi(slot_n)
            updates.append({"range": f"{col}{row_i2}", "values": [[stamp]]})

            # On stocke dans d_notes la trace du choix
            picked_txt = self.choices[choice_idx]
            old_note = str(row2.get("d_notes", "")).strip()
            merged = (old_note + " | " if old_note else "") + f"W12:{slot_n}:{picked_txt}"
            ws_defis.update(f"I{row_i2}", merged)

        if updates:
            ws_defis.batch_update(updates)

        # reload
        row_i3, row3 = get_defis_row(self.code, self.wk_key)
        done_after = defis_done_count(row3)

        awarded = False
        if done_before == 0 and done_after > 0:
            ok1, _ = add_points_by_action(self.code, "BLEETER", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            ok2, _ = add_points_by_action(self.code, "DEFI_HEBDO", 1, interaction.user.id, f"1er défi validé ({self.wk_key})", author_is_hg=True)
            awarded = bool(ok1 and ok2)

        if done_after >= 4 and str(row3.get("completed_at", "")).strip() == "":
            comp_stamp = now_fr().strftime("%Y-%m-%d %H:%M:%S")
            ws_defis.batch_update([
                {"range": f"G{row_i3}", "values": [[comp_stamp]]},
                {"range": f"H{row_i3}", "values": [[str(interaction.user.id)]]},
            ])

            add_points_by_action(self.code, "TOUS_DEFIS_HEBDO", 1, interaction.user.id, f"4/4 défis complétés ({self.wk_key})", author_is_hg=True)

            if ANNOUNCE_CHANNEL_ID:
                ch = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
                if ch:
                    await ch.send(catify(
                        f"🎉 **{self.vip_pseudo}** vient de finir les **4 défis** de la {self.wk_label} !\n"
                        f"😼 Mikasa tamponne le carnet VIP: **COMPLET**. 🐾",
                        chance=0.10
                    ))

        # finish
        for item in self.children:
            item.disabled = True

        emb = self._build_embed()
        extra = "🎁 Récompense donnée (1er défi de la semaine)." if awarded else "🧾 Récompense déjà prise cette semaine (ou slots déjà complets)."
        emb.add_field(name="✅ Enregistré", value=f"Progression: **{done_after}/4**\n{extra}", inline=False)
        emb.set_footer(text="Freestyle enregistré. Mikasa range les preuves. 🐾")

        await interaction.response.edit_message(embed=emb, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb:
                    emb.set_footer(text="Menu expiré • Relance `!defi CODE` 🐾")
                    await self.message.edit(embed=emb, view=self)
                else:
                    await self.message.edit(view=self)
            except Exception:
                pass

class Week12ChoiceButton(discord.ui.Button):
    def __init__(self, idx: int):
        super().__init__(label=f"❌ {idx+1}", style=discord.ButtonStyle.secondary, custom_id=f"w12_choice_{idx}")
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        if self.idx in view.selected:
            view.selected.remove(self.idx)
        else:
            if view.selected_count() >= 4:
                await interaction.response.send_message(catify("😾 Max **4** choix en semaine 12."), ephemeral=True)
                return
            view.selected.add(self.idx)
        await view._edit(interaction)
        
class Week12ValidateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ VALIDER", style=discord.ButtonStyle.success, custom_id="w12_commit")

    async def callback(self, interaction: discord.Interaction):
        view: DefiWeek12View = self.view  # type: ignore
        await view.commit_selected(interaction)
