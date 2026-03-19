"""
Notepad++ to Notion Migrator
Scans Notepad++ session/backup files and migrates their contents
to a Notion database as individual pages.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import json
import requests
import xml.etree.ElementTree as ET
import threading
from pathlib import Path
import time
import re
import configparser
import logging
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
MAX_BLOCK_TEXT_LENGTH = 1900  # Notion rich_text limit is 2000; leave headroom
MAX_CHILDREN_PER_REQUEST = 100  # Notion caps children[] on page creation
RATE_LIMIT_DELAY = 0.35  # ~3 requests/sec to stay under Notion's rate limit
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5  # seconds, multiplied each retry

LANGUAGE_MAP = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".xml": "xml",
    ".xsl": "xml",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".bat": "shell",  # Notion doesn't have "batch"
    ".cmd": "shell",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".sql": "sql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "plain text",
    ".ini": "plain text",
    ".cfg": "plain text",
    ".conf": "plain text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "c#",
    ".cpp": "c++",
    ".c": "c",
    ".h": "c",
    ".hpp": "c++",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".r": "r",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".scala": "scala",
    ".dart": "dart",
    ".vb": "visual basic",
    ".m": "objective-c",
    ".tf": "plain text",
    ".dockerfile": "docker",
    ".makefile": "makefile",
}

CODE_EXTENSIONS = set(LANGUAGE_MAP.keys())

SCRIPT_EXTENSIONS = {".bat", ".cmd", ".ps1", ".psm1", ".sh", ".bash", ".zsh"}


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------


def notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(method: str, url: str, headers: dict, json_body: dict | None = None) -> requests.Response:
    """Make a Notion API request with retry + exponential backoff."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(method, url, headers=headers, json=json_body, timeout=30)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", RETRY_BACKOFF * (attempt + 1)))
                time.sleep(retry_after)
                continue
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise last_exc or RuntimeError("Notion request failed after retries")


def classify_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in SCRIPT_EXTENSIONS:
        return "Script"
    if ext in CODE_EXTENSIONS:
        return "Code"
    if ext in {".md", ".markdown", ".txt", ".log", ".csv", ".tsv"}:
        return "Text"
    if ext in {".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
        return "Config"
    return "Text"


def get_language(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return LANGUAGE_MAP.get(ext, "plain text")


def split_content(content: str, max_length: int = MAX_BLOCK_TEXT_LENGTH) -> list[str]:
    """Split content into line-boundary-aware chunks."""
    chunks: list[str] = []
    lines = content.split("\n")
    current = ""

    for line in lines:
        # If a single line exceeds max_length, hard-wrap it
        if len(line) + 1 > max_length:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            for i in range(0, len(line), max_length):
                chunks.append(line[i : i + max_length])
            continue

        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current.rstrip("\n"))
            current = line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip("\n"))

    return chunks


def build_blocks(content: str, content_type: str, language: str) -> list[dict]:
    """Convert file content into a list of Notion block objects."""
    chunks = split_content(content)
    blocks: list[dict] = []
    is_code = content_type in ("Code", "Script", "Config")

    for chunk in chunks:
        if not chunk.strip():
            continue
        if is_code:
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}],
                        "language": language,
                    },
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}],
                    },
                }
            )
    return blocks


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_file_safe(filepath: str) -> str:
    """Read file content trying common encodings."""
    encodings = ["utf-8", "utf-8-sig", "utf-16", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError:
            break
    return ""


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------


class NotepadNotionMigrator:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Notepad++ to Notion Migrator")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        self.config_file = os.path.join(os.path.expanduser("~"), ".notepad_notion_config.ini")

        # State
        self.notion_token = tk.StringVar()
        self.notion_database_id = tk.StringVar()
        self.notes_data: list[dict] = []
        self.selected_indices: set[int] = set()
        self._migration_running = False

        self.load_config()
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Header.TLabel", font=("Arial", 15, "bold"))

        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)  # notes preview stretches
        main.rowconfigure(5, weight=0)

        # --- Title ---
        ttk.Label(main, text="Notepad++ to Notion Migration Tool", style="Header.TLabel").grid(
            row=0, column=0, pady=(0, 12)
        )

        # --- Config Frame ---
        cfg = ttk.LabelFrame(main, text="Notion Configuration", padding=8)
        cfg.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="Integration Token:").grid(row=0, column=0, sticky="w", pady=2)
        self.token_entry = ttk.Entry(cfg, textvariable=self.notion_token, show="*", width=60)
        self.token_entry.grid(row=0, column=1, sticky="ew", padx=(8, 4), pady=2)
        self.show_token_var = tk.BooleanVar()
        ttk.Checkbutton(cfg, text="Show", variable=self.show_token_var, command=self._toggle_token).grid(
            row=0, column=2, padx=4, pady=2
        )

        ttk.Label(cfg, text="Database ID (optional):").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(cfg, textvariable=self.notion_database_id, width=60).grid(
            row=1, column=1, sticky="ew", padx=(8, 4), pady=2
        )
        ttk.Button(cfg, text="Save Config", command=self.save_config).grid(row=1, column=2, padx=4, pady=2)

        ttk.Label(
            cfg,
            text="Leave Database ID empty to create a new database automatically. Token is stored in plaintext locally.",
            font=("Arial", 8),
            foreground="gray",
        ).grid(row=2, column=0, columnspan=3, pady=(4, 0))

        # --- Action Buttons ---
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=6)
        for i in range(4):
            actions.columnconfigure(i, weight=1)

        self.scan_btn = ttk.Button(actions, text="Scan Notepad++ Tabs", command=self._scan)
        self.scan_btn.grid(row=0, column=0, padx=2, sticky="ew")

        self.add_files_btn = ttk.Button(actions, text="Add Files Manually...", command=self._add_files)
        self.add_files_btn.grid(row=0, column=1, padx=2, sticky="ew")

        self.test_btn = ttk.Button(actions, text="Test Notion Connection", command=self._test_connection)
        self.test_btn.grid(row=0, column=2, padx=2, sticky="ew")

        self.clear_btn = ttk.Button(actions, text="Clear List", command=self._clear_list)
        self.clear_btn.grid(row=0, column=3, padx=2, sticky="ew")

        # --- Notes Preview (Treeview with checkboxes) ---
        preview = ttk.LabelFrame(main, text="Notes Preview", padding=6)
        preview.grid(row=3, column=0, sticky="nsew", pady=(0, 6))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)

        columns = ("name", "path", "size", "type", "status")
        self.tree = ttk.Treeview(preview, columns=columns, show="headings", selectmode="extended", height=12)
        col_widths = {"name": 180, "path": 260, "size": 80, "type": 70, "status": 90}
        col_labels = {"name": "Name", "path": "Path", "size": "Size", "type": "Type", "status": "Status"}
        for c in columns:
            self.tree.heading(c, text=col_labels[c])
            self.tree.column(c, width=col_widths[c], minwidth=50)

        vsb = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(preview, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Select helpers
        sel_frame = ttk.Frame(preview)
        sel_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(sel_frame, text="Select All", command=self._select_all).pack(side="left", padx=(0, 4))
        ttk.Button(sel_frame, text="Deselect All", command=self._deselect_all).pack(side="left", padx=(0, 4))
        ttk.Button(sel_frame, text="Remove Selected", command=self._remove_selected).pack(side="left")

        # --- Migration Controls ---
        mig = ttk.Frame(main)
        mig.grid(row=4, column=0, sticky="ew", pady=6)
        mig.columnconfigure(1, weight=1)

        self.migrate_btn = ttk.Button(mig, text="Migrate Selected to Notion", command=self._start_migration, state="disabled")
        self.migrate_btn.grid(row=0, column=0, padx=(0, 8))

        self.progress = ttk.Progressbar(mig, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew")

        # --- Log Panel ---
        log_frame = ttk.LabelFrame(main, text="Log", padding=4)
        log_frame.grid(row=5, column=0, sticky="ew", pady=(0, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=5, state="disabled", wrap="word", font=("Consolas", 9))
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.grid(row=0, column=0, sticky="ew")
        log_sb.grid(row=0, column=1, sticky="ns")

        # --- Status Bar ---
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var, foreground="gray").grid(row=6, column=0, sticky="w", pady=(4, 0))

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {level}: {msg}\n"
        self.root.after(0, self._append_log, line)

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, msg: str):
        self.root.after(0, lambda: self.status_var.set(msg))

    # ------------------------------------------------------------------
    # Token visibility
    # ------------------------------------------------------------------

    def _toggle_token(self):
        self.token_entry.config(show="" if self.show_token_var.get() else "*")

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def load_config(self):
        try:
            if not os.path.exists(self.config_file):
                return
            cfg = configparser.ConfigParser()
            cfg.read(self.config_file)
            if "Notion" in cfg:
                self.notion_token.set(cfg.get("Notion", "token", fallback=""))
                self.notion_database_id.set(cfg.get("Notion", "database_id", fallback=""))
        except Exception:
            pass

    def save_config(self):
        try:
            cfg = configparser.ConfigParser()
            cfg.add_section("Notion")
            cfg.set("Notion", "token", self.notion_token.get())
            cfg.set("Notion", "database_id", self.notion_database_id.get())
            with open(self.config_file, "w") as f:
                cfg.write(f)
            self._log("Configuration saved.")
            messagebox.showinfo("Saved", "Configuration saved.")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    # ------------------------------------------------------------------
    # Treeview helpers
    # ------------------------------------------------------------------

    def _refresh_migrate_button(self):
        has_items = len(self.tree.get_children()) > 0
        has_token = bool(self.notion_token.get().strip())
        state = "normal" if (has_items and has_token and not self._migration_running) else "disabled"
        self.migrate_btn.config(state=state)

    def _add_note_to_tree(self, note: dict):
        size = f"{len(note['content']):,} chars" if note["content"] else "0 chars"
        ctype = classify_content_type(note["name"])
        status = "Ready" if note["content"] else "Empty"
        self.tree.insert("", "end", values=(note["name"], note["path"], size, ctype, status))

    def _select_all(self):
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def _deselect_all(self):
        self.tree.selection_remove(*self.tree.get_children())

    def _remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        # Build a set of paths to remove
        paths_to_remove = set()
        for item in selected:
            vals = self.tree.item(item, "values")
            paths_to_remove.add(vals[1])  # path column
            self.tree.delete(item)
        self.notes_data = [n for n in self.notes_data if n["path"] not in paths_to_remove]
        self._refresh_migrate_button()
        self._set_status(f"{len(self.notes_data)} notes in list")

    def _clear_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.notes_data.clear()
        self._refresh_migrate_button()
        self._set_status("List cleared")

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan(self):
        if sys.platform != "win32":
            messagebox.showwarning("Platform", "Notepad++ session scanning is only supported on Windows.")
            return

        self._set_status("Scanning Notepad++ sessions...")
        self._log("Scanning Notepad++ session and backup files...")

        existing_paths = {n["path"] for n in self.notes_data}
        added = 0

        # --- Session file ---
        session_paths = [
            Path.home() / "AppData" / "Roaming" / "Notepad++" / "session.xml",
            Path.home() / "AppData" / "Local" / "Notepad++" / "session.xml",
            Path("C:/Program Files/Notepad++/session.xml"),
            Path("C:/Program Files (x86)/Notepad++/session.xml"),
        ]

        for sp in session_paths:
            if not sp.exists():
                continue
            self._log(f"Found session file: {sp}")
            try:
                tree = ET.parse(str(sp))
                for file_elem in tree.getroot().findall(".//File"):
                    fpath = file_elem.get("filename")
                    if not fpath or not os.path.exists(fpath) or fpath in existing_paths:
                        continue
                    content = read_file_safe(fpath)
                    note = {"name": os.path.basename(fpath), "path": fpath, "content": content, "source": "session"}
                    self.notes_data.append(note)
                    self._add_note_to_tree(note)
                    existing_paths.add(fpath)
                    added += 1
                break  # use the first valid session file
            except ET.ParseError as exc:
                self._log(f"XML parse error in {sp}: {exc}", "WARN")
            except Exception as exc:
                self._log(f"Error reading {sp}: {exc}", "WARN")

        # --- Backup files ---
        backup_dir = Path.home() / "AppData" / "Roaming" / "Notepad++" / "backup"
        if backup_dir.is_dir():
            self._log(f"Scanning backup directory: {backup_dir}")
            for fp in backup_dir.iterdir():
                if not fp.is_file():
                    continue
                fpath_str = str(fp)
                if fpath_str in existing_paths:
                    continue
                content = read_file_safe(fpath_str)
                display = fp.stem.replace("@", os.sep) if "@" in fp.stem else fp.name
                display = os.path.basename(display) or fp.name
                note = {"name": display, "path": fpath_str, "content": content, "source": "backup"}
                self.notes_data.append(note)
                self._add_note_to_tree(note)
                existing_paths.add(fpath_str)
                added += 1

        self._log(f"Scan complete. {added} new notes found ({len(self.notes_data)} total).")
        self._set_status(f"Found {len(self.notes_data)} notes total")
        self._refresh_migrate_button()

        if added == 0 and not self.notes_data:
            messagebox.showinfo("Scan", "No Notepad++ tabs found. Use 'Add Files Manually' to import files directly.")

    def _add_files(self):
        """Let user pick files manually."""
        paths = filedialog.askopenfilenames(
            title="Select files to migrate",
            filetypes=[
                ("All files", "*.*"),
                ("Text files", "*.txt"),
                ("Code files", "*.py *.js *.ts *.html *.css *.json *.xml *.yaml *.yml *.sh *.ps1 *.sql"),
            ],
        )
        if not paths:
            return

        existing = {n["path"] for n in self.notes_data}
        added = 0
        for p in paths:
            if p in existing:
                continue
            content = read_file_safe(p)
            note = {"name": os.path.basename(p), "path": p, "content": content, "source": "manual"}
            self.notes_data.append(note)
            self._add_note_to_tree(note)
            existing.add(p)
            added += 1

        self._log(f"Added {added} files manually.")
        self._set_status(f"{len(self.notes_data)} notes in list")
        self._refresh_migrate_button()

    # ------------------------------------------------------------------
    # Notion Connection Test
    # ------------------------------------------------------------------

    def _test_connection(self):
        token = self.notion_token.get().strip()
        if not token:
            messagebox.showerror("Error", "Enter your Notion integration token first.")
            return

        self._set_status("Testing Notion connection...")

        def _test():
            try:
                resp = notion_request("GET", f"{NOTION_BASE_URL}/users/me", notion_headers(token))
                if resp.status_code == 200:
                    user_data = resp.json()
                    name = user_data.get("name", "Unknown")
                    self._log(f"Connection successful. Authenticated as: {name}")
                    self._set_status("Connection OK")
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Connected as {name}"))
                    self.root.after(0, self._refresh_migrate_button)
                else:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    err_msg = body.get("message", resp.text[:200])
                    self._log(f"Connection failed ({resp.status_code}): {err_msg}", "ERROR")
                    self._set_status(f"Connection failed: {resp.status_code}")
                    self.root.after(0, lambda: messagebox.showerror("Error", f"{resp.status_code}: {err_msg}"))
            except Exception as exc:
                self._log(f"Connection error: {exc}", "ERROR")
                self._set_status("Connection error")
                self.root.after(0, lambda: messagebox.showerror("Error", str(exc)))

        threading.Thread(target=_test, daemon=True).start()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _start_migration(self):
        token = self.notion_token.get().strip()
        if not token:
            messagebox.showerror("Error", "Enter your Notion integration token first.")
            return

        # Determine which notes to migrate (selected, or all if none selected)
        selected_items = self.tree.selection()
        if selected_items:
            selected_paths = {self.tree.item(i, "values")[1] for i in selected_items}
            to_migrate = [n for n in self.notes_data if n["path"] in selected_paths]
        else:
            to_migrate = list(self.notes_data)

        if not to_migrate:
            messagebox.showerror("Error", "No notes to migrate.")
            return

        if not messagebox.askyesno("Confirm", f"Migrate {len(to_migrate)} notes to Notion?"):
            return

        self._migration_running = True
        self.migrate_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.add_files_btn.config(state="disabled")
        self.progress["maximum"] = len(to_migrate)
        self.progress["value"] = 0

        def _run():
            try:
                self._migrate(to_migrate, token)
            except Exception as exc:
                self._log(f"Migration error: {exc}", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("Error", str(exc)))
            finally:
                self._migration_running = False
                self.root.after(0, self._migration_done)

        threading.Thread(target=_run, daemon=True).start()

    def _migration_done(self):
        self.migrate_btn.config(state="normal")
        self.scan_btn.config(state="normal")
        self.test_btn.config(state="normal")
        self.add_files_btn.config(state="normal")
        self._refresh_migrate_button()

    def _ensure_database(self, headers: dict) -> str | None:
        """Return an existing or newly created database ID."""
        raw_id = self.notion_database_id.get().strip()
        if raw_id:
            clean = raw_id.replace("-", "")
            if len(clean) == 32 and all(c in "0123456789abcdef" for c in clean.lower()):
                formatted = f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
                self._log(f"Using existing database: {formatted}")
                return formatted
            else:
                self._log(f"Database ID '{raw_id}' looks invalid, will create a new one.", "WARN")

        # Search for an existing page to use as parent
        self._set_status("Creating Notion database...")
        self._log("Searching for a parent page...")

        resp = notion_request("POST", f"{NOTION_BASE_URL}/search", headers, {
            "filter": {"value": "page", "property": "object"},
            "page_size": 1,
        })

        parent_page_id = None
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                parent_page_id = results[0]["id"]
                self._log(f"Using existing page as parent: {parent_page_id}")

        if not parent_page_id:
            # Create a top-level page (workspace parent)
            self._log("No existing pages found. Creating a container page in workspace...")
            page_resp = notion_request("POST", f"{NOTION_BASE_URL}/pages", headers, {
                "parent": {"type": "workspace", "workspace": True},
                "properties": {
                    "title": {"title": [{"text": {"content": "Notepad++ Migration"}}]}
                },
            })
            if page_resp.status_code == 200:
                parent_page_id = page_resp.json()["id"]
                self._log(f"Container page created: {parent_page_id}")
            else:
                self._log(f"Failed to create container page: {page_resp.status_code} {page_resp.text[:200]}", "ERROR")
                return None

        # Create the database under the parent page
        db_payload = {
            "parent": {"page_id": parent_page_id},
            "title": [{"text": {"content": "Notepad++ Notes"}}],
            "properties": {
                "Name": {"title": {}},
                "Source File": {"rich_text": {}},
                "Import Date": {"date": {}},
                "Content Type": {
                    "select": {
                        "options": [
                            {"name": "Text", "color": "blue"},
                            {"name": "Code", "color": "green"},
                            {"name": "Script", "color": "orange"},
                            {"name": "Config", "color": "purple"},
                        ]
                    }
                },
            },
        }

        db_resp = notion_request("POST", f"{NOTION_BASE_URL}/databases", headers, db_payload)
        if db_resp.status_code == 200:
            db_id = db_resp.json()["id"]
            self._log(f"Database created: {db_id}")
            self.root.after(0, lambda: self.notion_database_id.set(db_id))
            self.root.after(0, self.save_config)
            return db_id
        else:
            self._log(f"Failed to create database: {db_resp.status_code} {db_resp.text[:300]}", "ERROR")
            return None

    def _migrate(self, notes: list[dict], token: str):
        headers = notion_headers(token)
        database_id = self._ensure_database(headers)
        if not database_id:
            self._set_status("Migration aborted: could not create/find database")
            return

        success = 0
        failed = 0

        for idx, note in enumerate(notes):
            self._set_status(f"Migrating ({idx + 1}/{len(notes)}): {note['name']}")
            self.root.after(0, lambda v=idx: self.progress.config(value=v))

            content_type = classify_content_type(note["name"])
            language = get_language(note["name"])
            all_blocks = build_blocks(note["content"], content_type, language) if note["content"] else []

            # First batch goes with the page creation (max 100)
            first_batch = all_blocks[:MAX_CHILDREN_PER_REQUEST]
            remaining = all_blocks[MAX_CHILDREN_PER_REQUEST:]

            page_data = {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": note["name"]}}]},
                    "Source File": {"rich_text": [{"text": {"content": note["path"][:2000]}}]},
                    "Import Date": {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
                    "Content Type": {"select": {"name": content_type}},
                },
                "children": first_batch,
            }

            try:
                resp = notion_request("POST", f"{NOTION_BASE_URL}/pages", headers, page_data)
                if resp.status_code != 200:
                    self._log(f"FAIL {note['name']}: {resp.status_code} {resp.text[:200]}", "ERROR")
                    failed += 1
                    self._update_tree_status(idx, "Failed")
                    time.sleep(RATE_LIMIT_DELAY)
                    continue

                page_id = resp.json()["id"]

                # Append remaining blocks in batches of 100
                while remaining:
                    batch = remaining[:MAX_CHILDREN_PER_REQUEST]
                    remaining = remaining[MAX_CHILDREN_PER_REQUEST:]
                    time.sleep(RATE_LIMIT_DELAY)
                    append_resp = notion_request(
                        "PATCH",
                        f"{NOTION_BASE_URL}/blocks/{page_id}/children",
                        headers,
                        {"children": batch},
                    )
                    if append_resp.status_code != 200:
                        self._log(
                            f"WARN: partial append failed for {note['name']}: {append_resp.status_code}",
                            "WARN",
                        )
                        break

                success += 1
                self._update_tree_status(idx, "Migrated")
                self._log(f"OK: {note['name']} ({len(all_blocks)} blocks)")

            except Exception as exc:
                failed += 1
                self._update_tree_status(idx, "Error")
                self._log(f"ERROR migrating {note['name']}: {exc}", "ERROR")

            time.sleep(RATE_LIMIT_DELAY)

        self.root.after(0, lambda: self.progress.config(value=len(notes)))
        self._set_status(f"Done: {success} migrated, {failed} failed")
        self._log(f"Migration complete. {success} succeeded, {failed} failed.")

        if success > 0:
            msg = f"Successfully migrated {success} of {len(notes)} notes."
            if database_id:
                msg += f"\n\nDatabase ID: {database_id}"
            self.root.after(0, lambda: messagebox.showinfo("Migration Complete", msg))

    def _update_tree_status(self, note_index: int, status: str):
        """Update the Status column for a given note index in the tree."""
        children = self.tree.get_children()
        # Find the matching tree item by path
        note_path = self.notes_data[note_index]["path"] if note_index < len(self.notes_data) else None
        if not note_path:
            return
        for item_id in children:
            vals = list(self.tree.item(item_id, "values"))
            if vals[1] == note_path:
                vals[4] = status
                self.root.after(0, lambda i=item_id, v=vals: self.tree.item(i, values=v))
                break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = NotepadNotionMigrator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
