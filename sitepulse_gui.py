import io
import json
import os
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import tkinter as tk
from tkinter import font as tkfont, filedialog, messagebox, ttk
from bs4 import BeautifulSoup
from PIL import Image, ImageTk

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
)

# ---------------------------------------------------------------------------
# Colors & fonts (matching the SitePulse design)
# ---------------------------------------------------------------------------
BG_DEEP = "#0a0a1f"
WAVE_VIOLET = "#8b5cf6"
WAVE_MAGENTA = "#c026d3"
CARD_BG = "#f2f1f7"
BRAND_BLUE = "#3457d5"
ACCENT_BLUE = "#2f6feb"
ACCENT_BLUE_HOVER = "#1f5bd6"
TEXT_DARK = "#1c1c28"
TEXT_MUTED = "#55566b"
ONLINE_GREEN = "#16a34a"
OFFLINE_RED = "#dc2626"
WARNING_AMBER = "#d97706"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Initial window size only -- the window is resizable now, and the canvas /
# cards resize with it (see _on_canvas_resize).
WINDOW_W, WINDOW_H = 660, 880
CARD_MAX_WIDTH = 540   # cards never grow wider than this, but they DO shrink
CARD_MIN_WIDTH = 320
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "sitepulse_history.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "sitepulse_settings.json")

DEFAULT_SETTINGS = {
    "request_timeout": 6,       # seconds
    "cert_warning_days": 30,    # warn if cert expires within this many days
    "default_interval": 60,     # seconds, for auto-monitoring
}

SECURITY_HEADERS = [
    ("Strict-Transport-Security", "Forces browsers to always use HTTPS."),
    ("Content-Security-Policy", "Restricts sources of scripts/styles to prevent XSS."),
    ("X-Frame-Options", "Prevents the page from being embedded in a clickjacking iframe."),
    ("X-Content-Type-Options", "Stops browsers from MIME-sniffing content types."),
    ("Referrer-Policy", "Controls how much referrer info is sent to other sites."),
    ("Permissions-Policy", "Restricts which browser features the page can use."),
]


def normalize_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    return raw_url


class SitePulseApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SitePulse — Website Security & Uptime Monitor")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.minsize(480, 500)
        # Allow the window to be resized and maximized.
        self.root.resizable(True, True)

        self.brand_font = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.tagline_font = tkfont.Font(family="Segoe UI", size=10)
        self.label_font = tkfont.Font(family="Segoe UI", size=10)
        self.label_bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.result_title_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        self.button_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.small_btn_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

        self.settings = self._load_settings()
        self.history = self._load_history()
        self._favicon_bytes = None
        self._current_result = None

        self.monitoring_active = False
        self.monitoring_job = None
        self.monitoring_url = None

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TNotebook", background=CARD_BG, borderwidth=0)
        style.configure("Card.TNotebook.Tab", padding=(14, 6), font=("Segoe UI", 9, "bold"))
        style.configure("Card.TFrame", background=CARD_BG)

        # ---------------- Top action bar (real toolbar, not on the canvas) ----------------
        top_bar = tk.Frame(root, bg=BG_DEEP, height=44)
        top_bar.pack(side="top", fill="x")
        top_bar.pack_propagate(False)
        tk.Button(top_bar, text="⚙ Settings", font=self.small_btn_font,
                  bg="#1e1b3a", fg="white", activebackground="#2a2652", activeforeground="white",
                  relief="flat", cursor="hand2", padx=12, pady=6,
                  command=self.open_settings_window).pack(side="right", padx=(0, 18), pady=8)
        tk.Button(top_bar, text="📜 History", font=self.small_btn_font,
                  bg="#1e1b3a", fg="white", activebackground="#2a2652", activeforeground="white",
                  relief="flat", cursor="hand2", padx=12, pady=8,
                  command=self.open_history_window).pack(side="right", padx=(0, 6), pady=8)

        # ---------------- Page tab bar (Check Website / Result) ----------------
        tab_bar = tk.Frame(root, bg="#e4e0f7", height=42)
        tab_bar.pack(side="top", fill="x")
        tab_bar.pack_propagate(False)

        self.tab_check_btn = tk.Button(
            tab_bar, text="🔍  Check Website", font=self.small_btn_font,
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=lambda: self.show_page("check")
        )
        self.tab_check_btn.pack(side="left", padx=(10, 4), pady=6)

        self.tab_result_btn = tk.Button(
            tab_bar, text="📊  Result", font=self.small_btn_font,
            relief="flat", cursor="hand2", padx=16, pady=8, state="disabled",
            command=lambda: self.show_page("result")
        )
        self.tab_result_btn.pack(side="left", padx=4, pady=6)

        # ---------------- Background canvas with ambient waves ----------------
        canvas_container = tk.Frame(root, bg=BG_DEEP)
        canvas_container.pack(fill="both", expand=True)

        # NOTE: no fixed width/height here -- the canvas fills whatever space
        # canvas_container gives it, and canvas_container fills the window.
        self.canvas = tk.Canvas(canvas_container, bg=BG_DEEP, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.v_scrollbar = tk.Scrollbar(canvas_container, orient="vertical",
                                         command=self.canvas.yview)
        self.v_scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        # Mouse-wheel scrolling (Windows/Mac use <MouseWheel>, Linux uses Button-4/5)
        self.canvas.bind("<Enter>", lambda e: self._bind_mousewheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())
        # Re-layout the waves and re-center/resize the cards whenever the
        # canvas changes size (window resize, maximize, restore...).
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self._wave_ids = []
        self._last_canvas_w = WINDOW_W
        self._last_canvas_h = WINDOW_H
        self.draw_waves()

        # ---------------- Main card (input) ----------------
        self.main_card = tk.Frame(self.canvas, bg=CARD_BG)
        self.main_window = self.canvas.create_window(
            WINDOW_W // 2, 16, window=self.main_card, anchor="n", width=CARD_MAX_WIDTH
        )

        tk.Label(self.main_card, text="🌐  SitePulse", font=self.brand_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(pady=(28, 4))
        tk.Label(self.main_card, text="Website Security & Uptime Monitor",
                 font=self.tagline_font, bg=CARD_BG, fg=TEXT_MUTED).pack(pady=(0, 18))

        self.url_var = tk.StringVar()
        entry = tk.Entry(self.main_card, textvariable=self.url_var, font=("Segoe UI", 11),
                          relief="flat", bg="white", fg=TEXT_DARK, insertbackground=TEXT_DARK)
        entry.configure(highlightthickness=1, highlightbackground="#b9c3f0", highlightcolor=ACCENT_BLUE)
        entry.pack(fill="x", padx=40, ipady=10)
        entry.bind("<Return>", lambda e: self.start_check())
        self._entry = entry
        self._set_placeholder("Enter Website URL (Example: google.com)")

        self.check_btn = tk.Button(
            self.main_card, text="Check Website", font=self.button_font,
            bg=ACCENT_BLUE, fg="white", activebackground=ACCENT_BLUE_HOVER,
            activeforeground="white", relief="flat", cursor="hand2",
            padx=24, pady=10, command=self.start_check
        )
        self.check_btn.pack(pady=(20, 10))

        # ---------------- Auto-monitoring controls ----------------
        monitor_row = tk.Frame(self.main_card, bg=CARD_BG)
        monitor_row.pack(pady=(0, 6))

        tk.Label(monitor_row, text="Every", font=self.label_font, bg=CARD_BG, fg=TEXT_MUTED).pack(side="left")
        self.interval_var = tk.StringVar(value=str(self.settings["default_interval"]))
        interval_spin = tk.Spinbox(monitor_row, from_=10, to=3600, increment=10, width=5,
                                    textvariable=self.interval_var, font=self.label_font,
                                    relief="flat", justify="center")
        interval_spin.pack(side="left", padx=6)
        tk.Label(monitor_row, text="sec", font=self.label_font, bg=CARD_BG, fg=TEXT_MUTED).pack(side="left", padx=(0, 14))

        self.monitor_btn = tk.Button(
            monitor_row, text="▶ Start Auto-Monitoring", font=self.small_btn_font,
            bg="#efe9fe", fg=BRAND_BLUE, activebackground="#e0d6fd", activeforeground=BRAND_BLUE,
            relief="flat", cursor="hand2", padx=12, pady=6,
            command=self.toggle_monitoring
        )
        self.monitor_btn.pack(side="left")

        self.monitor_status = tk.Label(self.main_card, text="", font=self.label_font,
                                        bg=CARD_BG, fg=TEXT_MUTED)
        self.monitor_status.pack(pady=(0, 6))

        self.error_label = tk.Label(self.main_card, text="", font=self.label_font,
                                     bg=CARD_BG, fg=OFFLINE_RED, wraplength=480)
        self.error_label.pack(pady=(0, 18))

        # ---------------- Result card ----------------
        self.result_card = tk.Frame(self.canvas, bg=CARD_BG)
        self.result_window = self.canvas.create_window(
            WINDOW_W // 2, 16, window=self.result_card, anchor="n", width=CARD_MAX_WIDTH
        )
        self.canvas.itemconfigure(self.result_window, state="hidden")

        tk.Label(self.result_card, text="Result", font=self.result_title_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(pady=(24, 10))

        self.favicon_label = tk.Label(self.result_card, bg=CARD_BG)
        self.favicon_label.pack(pady=(0, 8))

        self.res_url_label = tk.Label(self.result_card, text="", font=self.label_font,
                                       bg=CARD_BG, fg=TEXT_DARK, wraplength=480)
        self.res_url_label.pack()

        status_frame = tk.Frame(self.result_card, bg=CARD_BG)
        status_frame.pack(pady=(4, 14))
        tk.Label(status_frame, text="Status: ", font=self.label_bold_font,
                 bg=CARD_BG, fg=TEXT_DARK).pack(side="left")
        self.status_dot = tk.Canvas(status_frame, width=12, height=12, bg=CARD_BG,
                                     highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 5))
        self.status_text_label = tk.Label(status_frame, text="", font=self.label_bold_font, bg=CARD_BG)
        self.status_text_label.pack(side="left")

        # ---- Tabs: Overview / Security ----
        self.notebook = ttk.Notebook(self.result_card, style="Card.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=30, pady=(0, 10))

        overview_tab = tk.Frame(self.notebook, bg=CARD_BG)
        security_tab = tk.Frame(self.notebook, bg=CARD_BG)
        self.notebook.add(overview_tab, text="Overview")
        self.notebook.add(security_tab, text="Security")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._update_scrollregion())

        # Overview tab content
        self.detail_vars = {}
        for key, label in [
            ("code", "Status Code:"),
            ("time", "Response Time:"),
            ("ip", "IP Address:"),
            ("server", "Server:"),
            ("title", "Website Title:"),
        ]:
            row = tk.Frame(overview_tab, bg=CARD_BG)
            row.pack(fill="x", pady=4, anchor="w", padx=10)
            tk.Label(row, text=label, font=self.label_bold_font, bg=CARD_BG, fg=TEXT_DARK,
                     width=15, anchor="w").pack(side="left")
            val = tk.Label(row, text="", font=self.label_font, bg=CARD_BG, fg=TEXT_DARK,
                            wraplength=340, justify="left")
            val.pack(side="left", padx=(6, 0))
            self.detail_vars[key] = val

        # Security tab content — SSL block
        ssl_frame = tk.Frame(security_tab, bg=CARD_BG)
        ssl_frame.pack(fill="x", padx=10, pady=(12, 6))
        tk.Label(ssl_frame, text="SSL / TLS Certificate", font=self.label_bold_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(anchor="w")

        self.ssl_vars = {}
        for key, label in [
            ("status", "Status:"),
            ("issuer", "Issuer:"),
            ("expires", "Expires:"),
            ("days_left", "Days Remaining:"),
        ]:
            row = tk.Frame(ssl_frame, bg=CARD_BG)
            row.pack(fill="x", pady=2, anchor="w")
            tk.Label(row, text=label, font=self.label_font, bg=CARD_BG, fg=TEXT_MUTED,
                     width=15, anchor="w").pack(side="left")
            val = tk.Label(row, text="—", font=self.label_font, bg=CARD_BG, fg=TEXT_DARK,
                            wraplength=340, justify="left")
            val.pack(side="left")
            self.ssl_vars[key] = val

        sep2 = tk.Frame(security_tab, bg="#d9d9e3", height=1)
        sep2.pack(fill="x", padx=10, pady=10)

        # Security tab content — headers audit
        headers_frame = tk.Frame(security_tab, bg=CARD_BG)
        headers_frame.pack(fill="x", padx=10, pady=(0, 10))

        score_row = tk.Frame(headers_frame, bg=CARD_BG)
        score_row.pack(fill="x", anchor="w", pady=(0, 6))
        tk.Label(score_row, text="Security Headers Audit", font=self.label_bold_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(side="left")
        self.header_score_label = tk.Label(score_row, text="", font=self.label_bold_font, bg=CARD_BG)
        self.header_score_label.pack(side="right")

        self.header_rows_frame = tk.Frame(headers_frame, bg=CARD_BG)
        self.header_rows_frame.pack(fill="x")
        self.header_row_widgets = []

        result_btn_row = tk.Frame(self.result_card, bg=CARD_BG)
        result_btn_row.pack(pady=(4, 26))

        tk.Button(
            result_btn_row, text="🔁 Check Another Website", font=self.small_btn_font,
            bg="#efe9fe", fg=BRAND_BLUE, activebackground="#e0d6fd", activeforeground=BRAND_BLUE,
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=self.reset_for_new_check
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            result_btn_row, text="⬇  Export This Result as PDF", font=self.small_btn_font,
            bg=BRAND_BLUE, fg="white", activebackground="#28419e", activeforeground="white",
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=self.export_current_result_pdf
        ).pack(side="left")

        self._favicon_img = None

        self.show_page("check")

    # -----------------------------------------------------------------
    # Placeholder handling for the entry field
    # -----------------------------------------------------------------
    def _set_placeholder(self, text):
        self._entry.insert(0, text)
        self._entry.configure(fg="#8b8ca3")
        self._placeholder = text
        self._entry.bind("<FocusIn>", self._clear_placeholder)
        self._entry.bind("<FocusOut>", self._restore_placeholder)

    def _clear_placeholder(self, event):
        if self._entry.get() == self._placeholder:
            self._entry.delete(0, "end")
            self._entry.configure(fg=TEXT_DARK)

    def _restore_placeholder(self, event):
        if not self._entry.get().strip():
            self._set_placeholder(self._placeholder)

    def _get_url(self):
        val = self._entry.get().strip()
        if val == getattr(self, "_placeholder", None):
            return ""
        return val

    # -----------------------------------------------------------------
    # Background waves (redrawn on resize so they scale with the window)
    # -----------------------------------------------------------------
    def draw_waves(self):
        w = self.canvas.winfo_width() or WINDOW_W
        for wid in self._wave_ids:
            self.canvas.delete(wid)
        self._wave_ids = []

        # Wave x-coordinates are expressed as fractions of the canvas width
        # so they stretch to fill the available space instead of staying
        # pinned to the original 700px-wide layout.
        waves = [
            ([(-0.07, 500), (0.36, 380), (0.64, 580), (1.0, 460)], WAVE_MAGENTA, 2),
            ([(-0.07, 230), (0.40, 120), (0.69, 300), (1.0, 180)], WAVE_VIOLET, 2),
            ([(-0.07, 620), (0.36, 540), (0.71, 680), (1.0, 580)], WAVE_MAGENTA, 1),
            ([(-0.07, 100), (0.43, 30), (0.74, 170), (1.0, 70)], WAVE_VIOLET, 2),
        ]
        for points, color, width in waves:
            flat = []
            for fx, y in points:
                flat.extend([fx * w, y])
            wid = self.canvas.create_line(*flat, smooth=True, splinesteps=36,
                                           fill=color, width=width)
            self._wave_ids.append(wid)
            self.canvas.tag_lower(wid)

    def _on_canvas_resize(self, event):
        w, h = event.width, event.height
        if w == self._last_canvas_w and h == self._last_canvas_h:
            return
        self._last_canvas_w = w
        self._last_canvas_h = h

        # Card width scales with the window, capped between a min and max
        # so it neither gets crushed nor stretches absurdly wide.
        card_width = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, w - 60))
        self.canvas.coords(self.main_window, w // 2, 16)
        self.canvas.itemconfigure(self.main_window, width=card_width)
        self.canvas.coords(self.result_window, w // 2, 16)
        self.canvas.itemconfigure(self.result_window, width=card_width)

        self.draw_waves()
        self._update_scrollregion()

    # -----------------------------------------------------------------
    # Scrolling helpers
    # -----------------------------------------------------------------
    def _bind_mousewheel(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)      # Windows / Mac
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)  # Linux scroll up
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)  # Linux scroll down

    def _unbind_mousewheel(self):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event):
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")

    def _update_scrollregion(self):
        self.root.update_idletasks()
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        # Make sure the scrollregion is always at least as tall as the
        # visible canvas, so short content doesn't leave a scrollable gap.
        canvas_h = self.canvas.winfo_height()
        x0, y0, x1, y1 = bbox
        y1 = max(y1, y0 + canvas_h)
        self.canvas.configure(scrollregion=(x0, y0, x1, y1))

    # -----------------------------------------------------------------
    # Settings persistence
    # -----------------------------------------------------------------
    def _load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                settings.update(saved)
            except (json.JSONDecodeError, OSError):
                pass
        return settings

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except OSError:
            pass

    def open_settings_window(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("360x280")
        win.configure(bg=CARD_BG)
        win.resizable(False, False)

        tk.Label(win, text="Settings", font=self.result_title_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(pady=(18, 14))

        fields = {}
        specs = [
            ("request_timeout", "Request timeout (sec)"),
            ("cert_warning_days", "Warn if SSL cert expires within (days)"),
            ("default_interval", "Default monitoring interval (sec)"),
        ]
        for key, label in specs:
            row = tk.Frame(win, bg=CARD_BG)
            row.pack(fill="x", padx=24, pady=8)
            tk.Label(row, text=label, font=self.label_font, bg=CARD_BG, fg=TEXT_DARK,
                     wraplength=180, justify="left").pack(side="left")
            var = tk.StringVar(value=str(self.settings.get(key, DEFAULT_SETTINGS[key])))
            tk.Entry(row, textvariable=var, width=6, font=self.label_font,
                     relief="flat", highlightthickness=1,
                     highlightbackground="#b9c3f0").pack(side="right")
            fields[key] = var

        def save():
            try:
                new_settings = {k: int(v.get()) for k, v in fields.items()}
            except ValueError:
                messagebox.showerror("Invalid Input", "All settings must be whole numbers.")
                return
            self.settings.update(new_settings)
            self._save_settings()
            win.destroy()
            messagebox.showinfo("Saved", "Settings updated.")

        tk.Button(win, text="Save Settings", font=self.small_btn_font,
                  bg=ACCENT_BLUE, fg="white", relief="flat", cursor="hand2",
                  padx=16, pady=8, command=save).pack(pady=18)

    # -----------------------------------------------------------------
    # History persistence
    # -----------------------------------------------------------------
    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2)
        except OSError:
            pass

    def _add_to_history(self, data):
        entry = dict(data)
        entry["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history.insert(0, entry)
        self.history = self.history[:300]
        self._save_history()

    # -----------------------------------------------------------------
    # SSL certificate check
    # -----------------------------------------------------------------
    def get_ssl_info(self, hostname, port=443, timeout=6):
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()

            issuer = dict(x[0] for x in cert.get("issuer", []))
            not_after = cert.get("notAfter")
            expiry_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (expiry_dt - datetime.now(timezone.utc)).days

            warn_days = self.settings.get("cert_warning_days", 30)
            if days_left < 0:
                status = "EXPIRED"
            elif days_left <= warn_days:
                status = "EXPIRING SOON"
            else:
                status = "VALID"

            return {
                "valid": days_left >= 0,
                "status": status,
                "issuer": issuer.get("organizationName", issuer.get("commonName", "Unknown")),
                "expires": expiry_dt.strftime("%Y-%m-%d"),
                "days_left": days_left,
            }
        except Exception as e:
            return {
                "valid": False,
                "status": "UNAVAILABLE",
                "issuer": "N/A",
                "expires": "N/A",
                "days_left": "N/A",
                "error": str(e),
            }

    # -----------------------------------------------------------------
    # Security headers audit
    # -----------------------------------------------------------------
    def audit_security_headers(self, response_headers):
        results = []
        present_count = 0
        for header_name, description in SECURITY_HEADERS:
            value = response_headers.get(header_name)
            present = value is not None
            if present:
                present_count += 1
            results.append({
                "name": header_name,
                "present": present,
                "value": value if present else "Missing",
                "description": description,
            })
        score = round((present_count / len(SECURITY_HEADERS)) * 100)
        return {"headers": results, "score": score, "present_count": present_count,
                "total": len(SECURITY_HEADERS)}

    # -----------------------------------------------------------------
    # Check logic
    # -----------------------------------------------------------------
    def show_page(self, page):
        """Switch between the 'check' page (input form) and 'result' page."""
        if page == "result" and self._current_result is None:
            return  # nothing to show yet

        active_bg, active_fg = BRAND_BLUE, "white"
        inactive_bg, inactive_fg = "#e4e0f7", BRAND_BLUE

        if page == "check":
            self.canvas.itemconfigure(self.main_window, state="normal")
            self.canvas.itemconfigure(self.result_window, state="hidden")
            self.tab_check_btn.config(bg=active_bg, fg=active_fg, activebackground=active_bg, activeforeground="white")
            self.tab_result_btn.config(bg=inactive_bg, fg=inactive_fg, activebackground=inactive_bg, activeforeground=inactive_fg)
        else:
            self.canvas.itemconfigure(self.main_window, state="hidden")
            self.canvas.itemconfigure(self.result_window, state="normal")
            self.tab_result_btn.config(bg=active_bg, fg=active_fg, activebackground=active_bg, activeforeground="white")
            self.tab_check_btn.config(bg=inactive_bg, fg=inactive_fg, activebackground=inactive_bg, activeforeground=inactive_fg)

        self._update_scrollregion()
        self.canvas.yview_moveto(0)

    def reset_for_new_check(self):
        self.canvas.itemconfigure(self.result_window, state="hidden")
        self._current_result = None
        self.error_label.config(text="")
        self._entry.delete(0, "end")
        self._set_placeholder("Enter Website URL (Example: google.com)")
        self.tab_result_btn.config(state="disabled")
        self.show_page("check")
        self._entry.focus_set()

    def start_check(self):
        url = self._get_url()
        if not url:
            self.error_label.config(text="Please enter a website URL.")
            return

        self.error_label.config(text="")
        self.canvas.itemconfigure(self.result_window, state="hidden")
        self.check_btn.config(state="disabled", text="Checking...")

        thread = threading.Thread(target=self.check_url, args=(url,), daemon=True)
        thread.start()

    def check_url(self, raw_url, silent=False):
        url = normalize_url(raw_url)
        parsed = urlparse(url)
        data = {"url": url, "domain": parsed.netloc}
        timeout = self.settings.get("request_timeout", 6)

        try:
            start = time.time()
            response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            elapsed = round(time.time() - start, 3)

            data["online"] = response.status_code < 400
            data["status_code"] = response.status_code
            data["response_time"] = f"{elapsed} sec"
            data["server"] = response.headers.get("Server", "Unknown")
            data["final_url"] = response.url

            try:
                data["ip"] = socket.gethostbyname(urlparse(response.url).netloc)
            except socket.gaierror:
                data["ip"] = "Unknown"

            try:
                soup = BeautifulSoup(response.text, "html.parser")
                title_tag = soup.find("title")
                data["title"] = title_tag.get_text(strip=True) if title_tag else "N/A"
            except Exception:
                data["title"] = "N/A"

            data["favicon_url"] = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"

            # Security headers audit (based on the final response)
            data["security_audit"] = self.audit_security_headers(response.headers)

            # SSL certificate info (only meaningful for https)
            final_parsed = urlparse(response.url)
            if final_parsed.scheme == "https":
                data["ssl_info"] = self.get_ssl_info(final_parsed.hostname, timeout=timeout)
            else:
                data["ssl_info"] = {"valid": False, "status": "NOT HTTPS", "issuer": "N/A",
                                     "expires": "N/A", "days_left": "N/A"}

        except requests.exceptions.RequestException:
            data.update({
                "online": False, "status_code": "N/A", "response_time": "N/A",
                "server": "N/A", "ip": "N/A", "title": "N/A",
                "final_url": url,
                "favicon_url": f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64",
                "security_audit": {"headers": [
                    {"name": n, "present": False, "value": "Missing", "description": d}
                    for n, d in SECURITY_HEADERS
                ], "score": 0, "present_count": 0, "total": len(SECURITY_HEADERS)},
                "ssl_info": {"valid": False, "status": "UNAVAILABLE", "issuer": "N/A",
                             "expires": "N/A", "days_left": "N/A"},
            })

        self.root.after(0, self.render_result, data)

    def render_result(self, data, add_history=True):
        self.check_btn.config(state="normal", text="Check Website")
        self._current_result = data

        self.res_url_label.config(text=f"Website: {data.get('final_url', data['url'])}")

        is_online = data.get("online", False)
        self.status_dot.delete("all")
        color = ONLINE_GREEN if is_online else OFFLINE_RED
        self.status_dot.create_oval(2, 2, 10, 10, fill=color, outline=color)
        self.status_text_label.config(text="ONLINE" if is_online else "OFFLINE", fg=color)

        self.detail_vars["code"].config(text=str(data.get("status_code")))
        self.detail_vars["time"].config(text=str(data.get("response_time")))
        self.detail_vars["ip"].config(text=str(data.get("ip")))
        self.detail_vars["server"].config(text=str(data.get("server")))
        self.detail_vars["title"].config(text=str(data.get("title")))

        # SSL panel
        ssl_info = data.get("ssl_info", {})
        ssl_status = ssl_info.get("status", "N/A")
        ssl_color = {
            "VALID": ONLINE_GREEN, "EXPIRING SOON": WARNING_AMBER,
            "EXPIRED": OFFLINE_RED, "NOT HTTPS": TEXT_MUTED, "UNAVAILABLE": TEXT_MUTED,
        }.get(ssl_status, TEXT_DARK)
        self.ssl_vars["status"].config(text=ssl_status, fg=ssl_color)
        self.ssl_vars["issuer"].config(text=str(ssl_info.get("issuer", "N/A")), fg=TEXT_DARK)
        self.ssl_vars["expires"].config(text=str(ssl_info.get("expires", "N/A")), fg=TEXT_DARK)
        self.ssl_vars["days_left"].config(text=str(ssl_info.get("days_left", "N/A")), fg=TEXT_DARK)

        # Security headers panel
        audit = data.get("security_audit", {"headers": [], "score": 0})
        for w in self.header_row_widgets:
            w.destroy()
        self.header_row_widgets = []

        score = audit.get("score", 0)
        score_color = ONLINE_GREEN if score >= 70 else (WARNING_AMBER if score >= 40 else OFFLINE_RED)
        self.header_score_label.config(text=f"{score}%", fg=score_color)

        for h in audit.get("headers", []):
            row = tk.Frame(self.header_rows_frame, bg=CARD_BG)
            row.pack(fill="x", pady=2, anchor="w")
            mark = "✓" if h["present"] else "✗"
            mark_color = ONLINE_GREEN if h["present"] else OFFLINE_RED
            tk.Label(row, text=mark, font=self.label_bold_font, bg=CARD_BG, fg=mark_color,
                     width=2).pack(side="left")
            tk.Label(row, text=h["name"], font=self.label_font, bg=CARD_BG, fg=TEXT_DARK,
                     width=26, anchor="w").pack(side="left")
            self.header_row_widgets.append(row)

        self.load_favicon(data.get("favicon_url"))
        self.tab_result_btn.config(state="normal")
        self.show_page("result")

        if add_history:
            self._add_to_history(data)

    def load_favicon(self, favicon_url):
        def fetch():
            try:
                resp = requests.get(favicon_url, timeout=5)
                raw_bytes = resp.content
                img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
                img = img.resize((40, 40), Image.LANCZOS)
                self.root.after(0, self._set_favicon_image, img, raw_bytes)
            except Exception:
                self.root.after(0, self.favicon_label.config, {"image": "", "text": ""})
                self._favicon_bytes = None

        threading.Thread(target=fetch, daemon=True).start()

    def _set_favicon_image(self, pil_img, raw_bytes):
        self._favicon_img = ImageTk.PhotoImage(pil_img)
        self.favicon_label.config(image=self._favicon_img)
        self._favicon_bytes = raw_bytes

    # -----------------------------------------------------------------
    # Auto-monitoring
    # -----------------------------------------------------------------
    def toggle_monitoring(self):
        if self.monitoring_active:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        url = self._get_url()
        if not url:
            self.error_label.config(text="Enter a URL before starting monitoring.")
            return
        try:
            interval = int(self.interval_var.get())
            if interval < 5:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Interval", "Interval must be a whole number of seconds (5+).")
            return

        self.monitoring_active = True
        self.monitoring_url = url
        self.monitor_btn.config(text="⏹ Stop Monitoring", bg="#fde2e2", fg=OFFLINE_RED,
                                 activebackground="#fbcaca", activeforeground=OFFLINE_RED)
        self._entry.config(state="disabled")
        self.monitor_status.config(text=f"Monitoring {url} every {interval}s…")
        self._run_monitor_cycle(interval)

    def _run_monitor_cycle(self, interval):
        if not self.monitoring_active:
            return
        thread = threading.Thread(target=self.check_url, args=(self.monitoring_url,), daemon=True)
        thread.start()
        self.monitoring_job = self.root.after(interval * 1000, lambda: self._run_monitor_cycle(interval))

    def stop_monitoring(self):
        self.monitoring_active = False
        if self.monitoring_job:
            self.root.after_cancel(self.monitoring_job)
            self.monitoring_job = None
        self.monitor_btn.config(text="▶ Start Auto-Monitoring", bg="#efe9fe", fg=BRAND_BLUE,
                                 activebackground="#e0d6fd", activeforeground=BRAND_BLUE)
        self._entry.config(state="normal")
        self.monitor_status.config(text="Monitoring stopped.")

    # -----------------------------------------------------------------
    # History window
    # -----------------------------------------------------------------
    def open_history_window(self):
        win = tk.Toplevel(self.root)
        win.title("SitePulse — History")
        win.geometry("760x480")
        win.configure(bg=CARD_BG)

        header = tk.Frame(win, bg=CARD_BG)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="Check History", font=self.result_title_font,
                 bg=CARD_BG, fg=BRAND_BLUE).pack(side="left")

        btns = tk.Frame(header, bg=CARD_BG)
        btns.pack(side="right")
        tk.Button(btns, text="⬇ Export All as PDF", font=self.small_btn_font,
                  bg=BRAND_BLUE, fg="white", relief="flat", cursor="hand2",
                  padx=10, pady=5, command=self.export_history_pdf).pack(side="left", padx=4)
        tk.Button(btns, text="🗑 Clear History", font=self.small_btn_font,
                  bg=OFFLINE_RED, fg="white", relief="flat", cursor="hand2",
                  padx=10, pady=5, command=lambda: self.clear_history(win)).pack(side="left", padx=4)

        columns = ("time", "url", "status", "code", "response_time", "ssl")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=16)
        tree.heading("time", text="Checked At")
        tree.heading("url", text="Website")
        tree.heading("status", text="Status")
        tree.heading("code", text="Code")
        tree.heading("response_time", text="Time")
        tree.heading("ssl", text="SSL")
        tree.column("time", width=130)
        tree.column("url", width=230)
        tree.column("status", width=70, anchor="center")
        tree.column("code", width=50, anchor="center")
        tree.column("response_time", width=80, anchor="center")
        tree.column("ssl", width=100, anchor="center")
        tree.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        tree.tag_configure("online", foreground=ONLINE_GREEN)
        tree.tag_configure("offline", foreground=OFFLINE_RED)

        for entry in self.history:
            status = "ONLINE" if entry.get("online") else "OFFLINE"
            tag = "online" if entry.get("online") else "offline"
            ssl_status = entry.get("ssl_info", {}).get("status", "N/A")
            tree.insert("", "end", values=(
                entry.get("checked_at", ""),
                entry.get("final_url", entry.get("url", "")),
                status,
                entry.get("status_code", "N/A"),
                entry.get("response_time", "N/A"),
                ssl_status,
            ), tags=(tag,))

        def on_double_click(event):
            selected = tree.selection()
            if not selected:
                return
            index = tree.index(selected[0])
            entry = self.history[index]
            win.destroy()
            self.render_result(entry, add_history=False)

        tree.bind("<Double-1>", on_double_click)

        tk.Label(win, text="Double-click a row to reload that result above.",
                 font=self.label_font, bg=CARD_BG, fg=TEXT_MUTED).pack(pady=(0, 10))

    def clear_history(self, win):
        if not self.history:
            return
        if messagebox.askyesno("Clear History", "Delete all saved history? This cannot be undone."):
            self.history = []
            self._save_history()
            win.destroy()
            self.open_history_window()

    # -----------------------------------------------------------------
    # PDF export
    # -----------------------------------------------------------------
    def export_current_result_pdf(self):
        if not self._current_result:
            messagebox.showinfo("No Result", "Check a website first, then export the result.")
            return

        default_name = f"sitepulse_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", initialfile=default_name,
            filetypes=[("PDF files", "*.pdf")], title="Save Website Report"
        )
        if not path:
            return
        try:
            self._build_single_report_pdf(path, self._current_result, self._favicon_bytes)
            messagebox.showinfo("Exported", f"Report saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not create PDF:\n{e}")

    def export_history_pdf(self):
        if not self.history:
            messagebox.showinfo("No History", "No history to export yet.")
            return

        default_name = f"sitepulse_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", initialfile=default_name,
            filetypes=[("PDF files", "*.pdf")], title="Save History Report"
        )
        if not path:
            return
        try:
            self._build_history_report_pdf(path, self.history)
            messagebox.showinfo("Exported", f"History report saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not create PDF:\n{e}")

    def _build_single_report_pdf(self, path, data, favicon_bytes):
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(path, pagesize=letter,
                                 topMargin=0.7 * inch, bottomMargin=0.7 * inch)
        story = []

        story.append(Paragraph("SitePulse Website Report", styles["Title"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]))
        story.append(Spacer(1, 16))

        if favicon_bytes:
            try:
                img_reader = ImageReader(io.BytesIO(favicon_bytes))
                story.append(RLImage(img_reader, width=0.5 * inch, height=0.5 * inch))
                story.append(Spacer(1, 10))
            except Exception:
                pass

        is_online = data.get("online", False)
        status_color = colors.HexColor(ONLINE_GREEN) if is_online else colors.HexColor(OFFLINE_RED)
        status_style = styles["Heading2"].clone("status")
        status_style.textColor = status_color
        story.append(Paragraph("ONLINE" if is_online else "OFFLINE", status_style))
        story.append(Spacer(1, 12))

        rows = [
            ["Website", str(data.get("final_url", data.get("url", "")))],
            ["Status Code", str(data.get("status_code", "N/A"))],
            ["Response Time", str(data.get("response_time", "N/A"))],
            ["IP Address", str(data.get("ip", "N/A"))],
            ["Server", str(data.get("server", "N/A"))],
            ["Website Title", str(data.get("title", "N/A"))],
        ]
        table = Table(rows, colWidths=[1.6 * inch, 4.4 * inch])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(BRAND_BLUE)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9e3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        story.append(Spacer(1, 20))

        # SSL section
        ssl_info = data.get("ssl_info", {})
        story.append(Paragraph("SSL / TLS Certificate", styles["Heading2"]))
        ssl_rows = [
            ["Status", str(ssl_info.get("status", "N/A"))],
            ["Issuer", str(ssl_info.get("issuer", "N/A"))],
            ["Expires", str(ssl_info.get("expires", "N/A"))],
            ["Days Remaining", str(ssl_info.get("days_left", "N/A"))],
        ]
        ssl_table = Table(ssl_rows, colWidths=[1.6 * inch, 4.4 * inch])
        ssl_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9e3")),
        ]))
        story.append(ssl_table)
        story.append(Spacer(1, 20))

        # Security headers section
        audit = data.get("security_audit", {"headers": [], "score": 0})
        story.append(Paragraph(f"Security Headers Audit &mdash; Score: {audit.get('score', 0)}%",
                                styles["Heading2"]))
        header_rows = [["Header", "Status"]]
        for h in audit.get("headers", []):
            header_rows.append([h["name"], "Present" if h["present"] else "Missing"])
        header_table = Table(header_rows, colWidths=[3.5 * inch, 2.5 * inch], repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_BLUE)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9e3")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for i, h in enumerate(audit.get("headers", []), start=1):
            color = colors.HexColor(ONLINE_GREEN) if h["present"] else colors.HexColor(OFFLINE_RED)
            style_cmds.append(("TEXTCOLOR", (1, i), (1, i), color))
        header_table.setStyle(TableStyle(style_cmds))
        story.append(header_table)

        doc.build(story)

    def _build_history_report_pdf(self, path, history_entries):
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(path, pagesize=letter,
                                 topMargin=0.7 * inch, bottomMargin=0.7 * inch)
        story = []

        story.append(Paragraph("SitePulse Check History", styles["Title"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"&mdash; {len(history_entries)} record(s)", styles["Normal"]
        ))
        story.append(Spacer(1, 16))

        header = ["Checked At", "Website", "Status", "Code", "Time", "SSL"]
        rows = [header]
        for entry in history_entries:
            rows.append([
                entry.get("checked_at", ""),
                entry.get("final_url", entry.get("url", "")),
                "ONLINE" if entry.get("online") else "OFFLINE",
                str(entry.get("status_code", "N/A")),
                str(entry.get("response_time", "N/A")),
                str(entry.get("ssl_info", {}).get("status", "N/A")),
            ])

        table = Table(rows, colWidths=[1.0 * inch, 1.9 * inch, 0.7 * inch, 0.55 * inch, 0.7 * inch, 1.05 * inch],
                       repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_BLUE)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9e3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for i, entry in enumerate(history_entries, start=1):
            color = colors.HexColor(ONLINE_GREEN) if entry.get("online") else colors.HexColor(OFFLINE_RED)
            style_cmds.append(("TEXTCOLOR", (2, i), (2, i), color))
        table.setStyle(TableStyle(style_cmds))
        story.append(table)

        doc.build(story)


if __name__ == "__main__":
    root = tk.Tk()
    app = SitePulseApp(root)
    root.mainloop()