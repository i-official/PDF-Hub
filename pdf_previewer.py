import fitz
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import json
import requests
from packaging import version
import sys
import subprocess
import tempfile

# ===== UPDATE VERSION =====
def check_for_update():
    try:
        r = requests.get(UPDATE_INFO_URL, timeout=5)
        data = r.json()

        remote_version = data.get("version")
        exe_url = data.get("url")

        if version.parse(remote_version) > version.parse(APP_VERSION):
            return remote_version, exe_url

    except Exception as e:
        print("Update check failed:", e)

    return None, None

def download_new_exe(url):
    current_exe = sys.executable
    new_exe = current_exe.replace(".exe", "_new.exe")

    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(new_exe, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    return new_exe

def create_updater_bat(old_exe, new_exe):
    bat_path = os.path.join(tempfile.gettempdir(), "pdfpreviewer_updater.bat")

    bat_content = f"""@echo off
timeout /t 2 >nul
del "{old_exe}"
rename "{new_exe}" "{os.path.basename(old_exe)}"
start "" "{old_exe}"
"""

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    return bat_path

def run_update(new_exe):
    old_exe = sys.executable
    bat = create_updater_bat(old_exe, new_exe)
    subprocess.Popen(["cmd", "/c", bat], shell=True)
    sys.exit()

# =====  END UPDATE VERSION =====

APP_VERSION = "1.1.0"
UPDATE_INFO_URL = ""

APP_NAME = "PDF HUB-Previewer"
CONFIG_DIR = os.path.join(os.getenv("APPDATA"), APP_NAME)
os.makedirs(CONFIG_DIR, exist_ok=True)

INDEX_FILE = os.path.join(CONFIG_DIR, "pdf_index.json")
AUTO_REFRESH_MS = 3000


class PDFPreviewer:
    def __init__(self, root):
        self.root = root
        root.title("PDF Hub for B.Balykin v1.1.0")
        root.geometry("1400x900")

        # ===== TOP =====
        top = tk.Frame(root)
        top.pack(fill="x")

        tk.Button(top, text="📁 Сканировать папку", command=self.scan_folder).pack(side="left", padx=5)
        tk.Button(top, text="🔄 Обновить", command=self.manual_refresh).pack(side="left", padx=5)

        tk.Label(top, text="🔍 Поиск:").pack(side="left", padx=(20, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_list())
        tk.Entry(top, textvariable=self.search_var, width=30).pack(side="left")

        # ===== MAIN =====
        main = tk.Frame(root)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main)
        left.pack(side="left", fill="y")

        right = tk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        self.listbox = tk.Listbox(left, width=65)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.listbox.bind("<Double-Button-1>", self.open_pdf)

        self.canvas = tk.Canvas(right, bg="#2b2b2b")
        self.canvas.pack(fill="both", expand=True)

        # ===== DATA =====
        self.index = {}          # folder -> [pdfs]
        self.expanded = {}       # folder -> bool
        self.display_map = []
        self.auto_focus_index = None

        self.load_index()
        self.refresh_list()
        self.auto_refresh()

    # ===== STORAGE =====
    def load_index(self):
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                self.index = json.load(f)
                for folder in self.index:
                    self.expanded.setdefault(folder, True)

    def save_index(self):
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    # ===== SCAN =====
    def scan_folder(self):
        folder = filedialog.askdirectory(title="Выбери папку")
        if not folder:
            return

        self.index[folder] = self.scan_pdfs(folder)
        self.expanded[folder] = True
        self.save_index()
        self.refresh_list()

        messagebox.showinfo("Готово", f"Найдено PDF: {len(self.index[folder])}")

    def scan_pdfs(self, folder):
        pdfs = []
        for r, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdfs.append(os.path.join(r, f))
        return sorted(pdfs)

    # ===== AUTO REFRESH =====
    def auto_refresh(self):
        changed = False

        for folder in list(self.index.keys()):
            if not os.path.exists(folder):
                del self.index[folder]
                changed = True
                continue

            scanned = set(self.scan_pdfs(folder))
            current = set(self.index.get(folder, []))

            if scanned != current:
                self.index[folder] = sorted(scanned)
                changed = True

        if changed:
            self.save_index()
            self.refresh_list()

        self.root.after(AUTO_REFRESH_MS, self.auto_refresh)

    def manual_refresh(self):
        self.auto_refresh()

    # ===== LIST =====
    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        self.display_map.clear()
        self.auto_focus_index = None

        search = self.search_var.get().lower()

        # ===== GLOBAL SEARCH MODE =====
        if search:
            for folder, pdfs in self.index.items():
                matched = [
                    p for p in pdfs
                    if search in os.path.basename(p).lower()
                ]

                if not matched:
                    continue

                self.expanded[folder] = True
                self.listbox.insert(tk.END, f"🔍 📁 {folder}")
                self.display_map.append(("folder", folder))

                for pdf in matched:
                    name = os.path.basename(pdf)
                    self.listbox.insert(tk.END, f"    📄 {name}")
                    self.display_map.append(("pdf", pdf))

                    if self.auto_focus_index is None:
                        self.auto_focus_index = len(self.display_map) - 1

                self.listbox.insert(tk.END, "")
                self.display_map.append(("empty", None))

            self.apply_autofocus()
            return

        # ===== NORMAL MODE =====
        for folder, pdfs in self.index.items():
            icon = "➖" if self.expanded.get(folder, True) else "➕"
            self.listbox.insert(tk.END, f"{icon} 📁 {folder}")
            self.display_map.append(("folder", folder))

            if not self.expanded.get(folder, True):
                continue

            for pdf in pdfs:
                name = os.path.basename(pdf)
                self.listbox.insert(tk.END, f"    📄 {name}")
                self.display_map.append(("pdf", pdf))

            self.listbox.insert(tk.END, "")
            self.display_map.append(("empty", None))

    # ===== AUTOFOCUS =====
    def apply_autofocus(self):
        if self.auto_focus_index is None:
            return

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.auto_focus_index)
        self.listbox.see(self.auto_focus_index)

        item_type, value = self.display_map[self.auto_focus_index]
        if item_type == "pdf":
            self.show_preview(value)

    # ===== EVENTS =====
    def on_select(self, event):
        if self.search_var.get():
            return

        if not self.listbox.curselection():
            return

        idx = self.listbox.curselection()[0]
        item_type, value = self.display_map[idx]

        if item_type == "folder":
            self.expanded[value] = not self.expanded.get(value, True)
            self.refresh_list()
            return

        if item_type == "pdf":
            self.show_preview(value)

    # ===== PREVIEW =====
    def show_preview(self, path):
        try:
            doc = fitz.open(path)
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.thumbnail((900, 1200))

            self.tk_img = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(20, 20, anchor="nw", image=self.tk_img)
        except Exception as e:
            self.canvas.delete("all")
            self.canvas.create_text(300, 200, text=str(e), fill="white")

    # ===== OPEN =====
    def open_pdf(self, event):
        if not self.listbox.curselection():
            return
        idx = self.listbox.curselection()[0]
        item_type, value = self.display_map[idx]
        if item_type == "pdf":
            os.startfile(value)


if __name__ == "__main__":
    root = tk.Tk()

    remote_version, exe_url = check_for_update()
    if remote_version:
        if messagebox.askyesno(
            "Обновление доступно",
            f"Найдена новая версия {remote_version}\n\nОбновить сейчас?"
        ):
            new_exe = download_new_exe(exe_url)
            run_update(new_exe)

    PDFPreviewer(root)
    root.mainloop()