"""Help > About Latchwork: version, build, Python and Tk, the repository."""
import platform
import tkinter as tk
import webbrowser
from tkinter import ttk

from .version import REPO_URL, VERSION, build
from .widgets import BG, SMALL_FONT, UI_FONT, tip

LICENSE = "MIT License, © 2026 Tim Biggin"


class AboutDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("About Latchwork")
        self.configure(bg=BG, padx=20, pady=16)
        self.resizable(False, False)
        self.transient(parent)

        tk.Label(self, text="Latchwork", font=("Segoe UI", 16, "bold"), bg=BG,
                 anchor="w").pack(fill="x")
        tk.Label(self, text="Version " + VERSION, font=("Segoe UI", 11), bg=BG,
                 anchor="w").pack(fill="x")
        tk.Label(self, text=build(), font=SMALL_FONT, fg="#555", bg=BG,
                 anchor="w").pack(fill="x")
        tk.Label(self, text="Latch-hook rug planning from pixel art.", font=UI_FONT, bg=BG,
                 anchor="w").pack(fill="x", pady=(10, 0))

        grid = tk.Frame(self, bg=BG)
        grid.pack(fill="x", pady=(10, 0))
        rows = [("Python", "%s (%s)" % (platform.python_version(), platform.system())),
                ("Tk", str(self.tk.call("info", "patchlevel")))]
        for r, (name, value) in enumerate(rows):
            tk.Label(grid, text=name, font=UI_FONT, fg="#555", bg=BG,
                     anchor="w").grid(row=r, column=0, sticky="w", padx=(0, 12))
            tk.Label(grid, text=value, font=UI_FONT, bg=BG, anchor="w").grid(row=r, column=1,
                                                                            sticky="w")

        # a named link, underlined while pointed at; the address shows on hover
        link = tk.Label(self, text="Latchwork on GitHub ↗", font=UI_FONT, fg="#0B5FB0",
                        bg=BG, cursor="hand2")
        link.pack(anchor="w", pady=(10, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))
        link.bind("<Enter>", lambda e: link.config(font=UI_FONT + ("underline",)), add="+")
        link.bind("<Leave>", lambda e: link.config(font=UI_FONT), add="+")
        tip(link, REPO_URL)
        tk.Label(self, text=LICENSE, font=SMALL_FONT, fg="#555", bg=BG,
                 anchor="w").pack(fill="x")

        close = ttk.Button(self, text="Close", command=self.destroy)
        close.pack(side="right", pady=(14, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 80, parent.winfo_rooty() + 80))
        self.grab_set()
        close.focus_set()
