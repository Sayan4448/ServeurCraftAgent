"""Vues « Bannis », « Opérateurs » et « Whitelist » (réutilisées par l'onglet
serveurs et la fenêtre serveur). Fonctionnent serveur lancé ou arrêté."""
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..core import banlist
from ..i18n import t
from . import theme


class _ListView(ctk.CTkFrame):
    """Base : champ pseudo + bouton en haut, liste défilante dessous."""

    def __init__(self, master, get_ctx, placeholder, action_text):
        super().__init__(master, fg_color="transparent")
        self.get_ctx = get_ctx        # -> (server_dir, proc, online_mode)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # rangée 0 : en-tête éventuel
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        top.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(top, placeholder_text=placeholder,
                                  height=30, fg_color=theme.PANEL_2,
                                  border_color=theme.BORDER,
                                  text_color=theme.TEXT)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self._add())
        ctk.CTkButton(top, text=action_text, width=70, height=30,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._add).grid(row=0, column=1)
        self.list = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.HOVER)
        self.list.grid(row=2, column=0, sticky="nsew")
        self.list.grid_columnconfigure(0, weight=1)

    def _later(self):
        """Serveur lancé : il réécrit ses JSON un instant après la commande."""
        self.refresh()
        self.after(900, self.refresh)
        self.after(2500, self.refresh)

    def _empty(self, text):
        ctk.CTkLabel(self.list, text=text, text_color=theme.MUTED,
                     wraplength=190, justify="left").grid(
            row=0, column=0, sticky="w", padx=6, pady=6)

    def _clear(self):
        for w in self.list.winfo_children():
            w.destroy()


class BansView(_ListView):
    def __init__(self, master, get_ctx):
        super().__init__(master, get_ctx, t("bans_ph"), t("bans_add"))

    def _add(self):
        name = self.entry.get().strip()
        ctx = self.get_ctx()
        if not name or not ctx:
            return
        d, proc, online = ctx
        dlg = ctk.CTkInputDialog(text=t("ban_reason", name=name),
                                 title=t("reason_title"))
        reason = dlg.get_input()
        if reason is None:
            return
        banlist.ban(d, name, reason.strip(), proc=proc, online_mode=online)
        self.entry.delete(0, "end")
        self._later()

    def refresh(self):
        self._clear()
        ctx = self.get_ctx()
        if not ctx:
            return
        d, proc, online = ctx
        bans = banlist.list_bans(d)
        if not bans:
            self._empty(t("bans_empty"))
            return
        ops = {o["name"].lower() for o in banlist.list_ops(d)}
        for i, b in enumerate(bans):
            card = ctk.CTkFrame(self.list, fg_color=theme.PANEL_2,
                                corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            card.grid_columnconfigure(0, weight=1)
            title = ("🌐 " if b["ip"] else "🔨 ") + b["name"]
            ctk.CTkLabel(card, text=title, font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=10, pady=(8, 0))
            sub = b["reason"] or t("bans_no_reason")
            if b["created"]:
                sub += f"\n{b['created'][:16]}"
            ctk.CTkLabel(card, text=sub, font=(theme.FONT, 10),
                         text_color=theme.MUTED, anchor="w", justify="left",
                         wraplength=180).grid(row=1, column=0, sticky="w",
                                              padx=10)
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
            btns.grid_columnconfigure((0, 1), weight=1)
            if not b["ip"]:
                is_op = b["name"].lower() in ops
                ctk.CTkButton(
                    btns, text=("⭐ " + t("op_yes")) if is_op else t("op"),
                    height=26, font=(theme.FONT, 11),
                    fg_color=theme.ORANGE if is_op else theme.PANEL,
                    hover_color=theme.HOVER,
                    text_color="#ffffff" if is_op else theme.TEXT,
                    command=lambda e=b, o=is_op: self._toggle_op(e, o)).grid(
                    row=0, column=0, sticky="ew", padx=(0, 3))
            ctk.CTkButton(
                btns, text="🕊 " + t("unban_btn"), height=26,
                font=(theme.FONT, 11), fg_color=theme.GREEN,
                hover_color=theme.GREEN_HOVER, text_color=theme.ON_GREEN,
                command=lambda e=b: self._unban(e)).grid(
                row=0, column=1, sticky="ew", padx=(3, 0))

    def _toggle_op(self, entry, is_op):
        d, proc, online = self.get_ctx()
        if is_op:
            banlist.deop(d, entry["name"], proc=proc)
        else:
            banlist.op(d, entry["name"], entry.get("uuid", ""), proc=proc,
                       online_mode=online)
        self._later()

    def _unban(self, entry):
        d, proc, _online = self.get_ctx()
        if messagebox.askyesno(t("unban_btn"),
                               t("unban_confirm", name=entry["name"]),
                               parent=self):
            banlist.unban(d, entry, proc=proc)
            self._later()


class OpsView(_ListView):
    def __init__(self, master, get_ctx):
        super().__init__(master, get_ctx, t("bans_ph"), "⭐ OP")

    def _add(self):
        name = self.entry.get().strip()
        ctx = self.get_ctx()
        if not name or not ctx:
            return
        d, proc, online = ctx
        banlist.op(d, name, proc=proc, online_mode=online)
        self.entry.delete(0, "end")
        self._later()

    def refresh(self):
        self._clear()
        ctx = self.get_ctx()
        if not ctx:
            return
        d, proc, _online = ctx
        ops = banlist.list_ops(d)
        if not ops:
            self._empty(t("ops_empty"))
            return
        for i, o in enumerate(ops):
            card = ctk.CTkFrame(self.list, fg_color=theme.PANEL_2,
                                corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=f"⭐ {o['name']}",
                         font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=10, pady=8)
            ctk.CTkButton(card, text=t("deop"), width=90, height=26,
                          font=(theme.FONT, 11), fg_color=theme.PANEL,
                          hover_color=theme.HOVER, text_color=theme.TEXT,
                          command=lambda n=o["name"]: (
                              banlist.deop(d, n, proc=proc),
                              self._later())).grid(row=0, column=1, padx=8)


class WhitelistView(_ListView):
    """Liste blanche : interrupteur + joueurs autorisés. Serveur lancé :
    commandes `whitelist …` ; arrêté : `whitelist.json` et
    `server.properties` édités directement."""

    def __init__(self, master, get_ctx):
        super().__init__(master, get_ctx, t("wl_ph"), t("wl_add"))
        self.switch = ctk.CTkSwitch(
            self, text=t("wl_switch"), text_color=theme.TEXT,
            font=(theme.FONT, 12, "bold"), progress_color=theme.GREEN,
            command=self._toggle)
        self.switch.grid(row=0, column=0, sticky="w", padx=6, pady=(0, 8))

    def _toggle(self):
        ctx = self.get_ctx()
        if not ctx:
            self.switch.deselect()
            return
        d, proc, _online = ctx
        banlist.set_whitelist(d, bool(self.switch.get()), proc=proc)
        self.refresh()

    def _add(self):
        name = self.entry.get().strip()
        ctx = self.get_ctx()
        if not name or not ctx:
            return
        d, proc, online = ctx
        banlist.whitelist_add(d, name, proc=proc, online_mode=online)
        self.entry.delete(0, "end")
        self._later()

    def _remove(self, name):
        ctx = self.get_ctx()
        if ctx:
            banlist.whitelist_remove(ctx[0], name, proc=ctx[1])
            self._later()

    def refresh(self):
        self._clear()
        ctx = self.get_ctx()
        if not ctx:
            return
        d, _proc, _online = ctx
        enabled = banlist.whitelist_enabled(d)
        (self.switch.select if enabled else self.switch.deselect)()
        entries = banlist.list_whitelist(d)
        if not entries:
            self._empty(t("wl_empty") if enabled else t("wl_off_hint"))
            return
        for i, e in enumerate(entries):
            card = ctk.CTkFrame(self.list, fg_color=theme.PANEL_2,
                                corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=e["name"],
                         font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=10, pady=8)
            ctk.CTkButton(card, text=t("wl_remove"), width=80, height=26,
                          font=(theme.FONT, 11), fg_color=theme.PANEL,
                          hover_color=theme.RED, text_color=theme.TEXT,
                          command=lambda n=e["name"]: self._remove(n)).grid(
                row=0, column=1, padx=8)
        if not enabled:
            ctk.CTkLabel(self.list, text=t("wl_off_hint"),
                         text_color=theme.MUTED, font=(theme.FONT, 10),
                         wraplength=190, justify="left").grid(
                row=len(entries), column=0, sticky="w", padx=6, pady=6)


def ctx_for(proc):
    """Contexte (dossier, process, online-mode) d'un ServerProcess."""
    if not proc:
        return None
    return (Path(proc.path), proc, proc.meta.get("accounts") == "premium")
