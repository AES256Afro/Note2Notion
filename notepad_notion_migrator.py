import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import json
import requests
import xml.etree.ElementTree as ET
import threading
from pathlib import Path
import time
import re
import configparser

class NotepadNotionMigrator:
    def __init__(self, root):
        self.root = root
        self.root.title("Notepad++ to Notion Migrator")
        self.root.geometry("800x600")
        
        # Configuration file path
        self.config_file = os.path.join(os.path.expanduser("~"), ".notepad_notion_config.ini")
        
        # Variables
        self.notion_token = tk.StringVar()
        self.notion_database_id = tk.StringVar()
        self.notes_data = []
        
        # Load saved configuration
        self.load_config()
        
        self.setup_ui()
        
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Notepad++ to Notion Migration Tool", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Notion API Configuration
        config_frame = ttk.LabelFrame(main_frame, text="Notion Configuration", padding="10")
        config_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        ttk.Label(config_frame, text="Notion Integration Token:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        token_entry = ttk.Entry(config_frame, textvariable=self.notion_token, show="*", width=50)
        token_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 5), pady=(0, 5))
        
        # Show/Hide token button
        self.show_token = tk.BooleanVar()
        show_btn = ttk.Checkbutton(config_frame, text="Show", variable=self.show_token,
                                  command=self.toggle_token_visibility)
        show_btn.grid(row=0, column=2, padx=(5, 0), pady=(0, 5))
        
        ttk.Label(config_frame, text="Database ID (optional):").grid(row=1, column=0, sticky=tk.W)
        db_entry = ttk.Entry(config_frame, textvariable=self.notion_database_id, width=50)
        db_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(10, 5))
        
        # Save configuration button
        save_btn = ttk.Button(config_frame, text="Save Config", command=self.save_config)
        save_btn.grid(row=1, column=2, padx=(5, 0))
        
        # Store reference to token entry for show/hide functionality
        self.token_entry = token_entry
        
        # Help text
        help_text = ttk.Label(config_frame, text="Leave Database ID empty to create a new database automatically", 
                             font=("Arial", 8), foreground="gray")
        help_text.grid(row=2, column=0, columnspan=3, pady=(5, 0))
        
        # Action buttons frame
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        
        # Scan button
        self.scan_btn = ttk.Button(action_frame, text="Scan Notepad++ Tabs", 
                                  command=self.scan_notepad_tabs)
        self.scan_btn.grid(row=0, column=0, padx=(0, 5), sticky=(tk.W, tk.E))
        
        # Test connection button
        self.test_btn = ttk.Button(action_frame, text="Test Notion Connection", 
                                  command=self.test_notion_connection)
        self.test_btn.grid(row=0, column=1, padx=(5, 0), sticky=(tk.W, tk.E))
        
        # Notes preview frame
        preview_frame = ttk.LabelFrame(main_frame, text="Notes Preview", padding="10")
        preview_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        
        # Treeview for notes
        columns = ("Name", "Path", "Size", "Status")
        self.notes_tree = ttk.Treeview(preview_frame, columns=columns, show="headings", height=10)
        
        for col in columns:
            self.notes_tree.heading(col, text=col)
            self.notes_tree.column(col, width=150)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.notes_tree.yview)
        h_scrollbar = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self.notes_tree.xview)
        self.notes_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.notes_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Migration controls
        migration_frame = ttk.Frame(main_frame)
        migration_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        migration_frame.columnconfigure(1, weight=1)
        
        self.migrate_btn = ttk.Button(migration_frame, text="Migrate to Notion", 
                                     command=self.start_migration, state="disabled")
        self.migrate_btn.grid(row=0, column=0, padx=(0, 10))
        
        # Progress bar
        self.progress = ttk.Progressbar(migration_frame, mode='determinate')
        self.progress.grid(row=0, column=1, sticky=(tk.W, tk.E))
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Ready to scan Notepad++ tabs")
        self.status_label.grid(row=5, column=0, columnspan=3, pady=(10, 0))
        
    def scan_notepad_tabs(self):
        """Scan for active Notepad++ tabs"""
        self.status_label.config(text="Scanning Notepad++ tabs...")
        self.notes_data.clear()
        
        # Clear existing items
        for item in self.notes_tree.get_children():
            self.notes_tree.delete(item)
        
        try:
            # Method 1: Check Notepad++ session file
            session_notes = self.scan_session_file()
            
            # Method 2: Scan common Notepad++ temp locations
            temp_notes = self.scan_temp_files()
            
            # Combine and deduplicate
            all_notes = session_notes + temp_notes
            seen_paths = set()
            
            for note in all_notes:
                if note['path'] not in seen_paths:
                    self.notes_data.append(note)
                    seen_paths.add(note['path'])
                    
                    # Add to treeview
                    status = "Ready" if note['content'] else "Empty"
                    size_str = f"{len(note['content'])} chars" if note['content'] else "0 chars"
                    
                    self.notes_tree.insert("", "end", values=(
                        note['name'],
                        note['path'],
                        size_str,
                        status
                    ))
            
            if self.notes_data:
                self.status_label.config(text=f"Found {len(self.notes_data)} notes")
                if self.notion_token.get():
                    self.migrate_btn.config(state="normal")
            else:
                self.status_label.config(text="No Notepad++ tabs found. Make sure Notepad++ is running with open files.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Error scanning Notepad++ tabs: {str(e)}")
            self.status_label.config(text="Error scanning tabs")
    
    def scan_session_file(self):
        """Scan Notepad++ session.xml file for open tabs"""
        notes = []
        
        # Common Notepad++ config locations
        possible_paths = [
            os.path.expanduser("~\\AppData\\Roaming\\Notepad++\\session.xml"),
            os.path.expanduser("~\\AppData\\Local\\Notepad++\\session.xml"),
            "C:\\Program Files\\Notepad++\\session.xml",
            "C:\\Program Files (x86)\\Notepad++\\session.xml"
        ]
        
        for session_path in possible_paths:
            if os.path.exists(session_path):
                try:
                    tree = ET.parse(session_path)
                    root = tree.getroot()
                    
                    # Find all File elements
                    for file_elem in root.findall(".//File"):
                        filename = file_elem.get("filename")
                        if filename and os.path.exists(filename):
                            content = self.read_file_safe(filename)
                            name = os.path.basename(filename)
                            
                            notes.append({
                                'name': name,
                                'path': filename,
                                'content': content,
                                'source': 'session'
                            })
                    break
                    
                except ET.ParseError:
                    continue
                except Exception:
                    continue
                    
        return notes
    
    def scan_temp_files(self):
        """Scan for Notepad++ backup/temp files"""
        notes = []
        
        backup_path = os.path.expanduser("~\\AppData\\Roaming\\Notepad++\\backup")
        if os.path.exists(backup_path):
            try:
                for filename in os.listdir(backup_path):
                    if filename.endswith(".bak"):
                        filepath = os.path.join(backup_path, filename)
                        content = self.read_file_safe(filepath)
                        
                        # Extract original filename from backup name
                        original_name = filename.replace("@", "\\").replace(".bak", "")
                        display_name = os.path.basename(original_name) or filename
                        
                        notes.append({
                            'name': display_name,
                            'path': filepath,
                            'content': content,
                            'source': 'backup'
                        })
            except Exception:
                pass
                
        return notes
    
    def read_file_safe(self, filepath):
        """Safely read file content with encoding detection"""
        encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                break
                
        return ""
    
    def test_notion_connection(self):
        """Test connection to Notion API"""
        if not self.notion_token.get():
            messagebox.showerror("Error", "Please enter your Notion integration token")
            return
            
        self.status_label.config(text="Testing Notion connection...")
        
        def test_connection():
            try:
                headers = {
                    "Authorization": f"Bearer {self.notion_token.get()}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json"
                }
                
                response = requests.get("https://api.notion.com/v1/users/me", headers=headers)
                
                if response.status_code == 200:
                    self.root.after(0, lambda: self.status_label.config(text="Notion connection successful!"))
                    self.root.after(0, lambda: messagebox.showinfo("Success", "Connection to Notion API successful!"))
                    if self.notes_data:
                        self.root.after(0, lambda: self.migrate_btn.config(state="normal"))
                else:
                    error_msg = f"Connection failed: {response.status_code}"
                    self.root.after(0, lambda: self.status_label.config(text=error_msg))
                    self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
                    
            except Exception as e:
                error_msg = f"Connection error: {str(e)}"
                self.root.after(0, lambda: self.status_label.config(text=error_msg))
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        threading.Thread(target=test_connection, daemon=True).start()
    
    def start_migration(self):
        """Start the migration process"""
        if not self.notion_token.get():
            messagebox.showerror("Error", "Please enter your Notion integration token")
            return
            
        if not self.notes_data:
            messagebox.showerror("Error", "No notes found. Please scan for tabs first.")
            return
        
        # Confirm migration
        result = messagebox.askyesno(
            "Confirm Migration", 
            f"This will create {len(self.notes_data)} new pages in Notion. Continue?"
        )
        
        if not result:
            return
            
        self.migrate_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        
        self.progress['maximum'] = len(self.notes_data)
        self.progress['value'] = 0
        
        def migrate():
            try:
                self.migrate_notes()
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Migration Error", str(e)))
            finally:
                self.root.after(0, self.migration_complete)
        
        threading.Thread(target=migrate, daemon=True).start()
    
    def create_database(self, headers):
        """Create a new database for storing notes"""
        try:
            # First, search for an existing page to use as parent
            search_response = requests.post(
                "https://api.notion.com/v1/search",
                headers=headers,
                json={
                    "filter": {
                        "value": "page",
                        "property": "object"
                    },
                    "page_size": 1
                }
            )
            
            parent_page_id = None
            if search_response.status_code == 200:
                search_data = search_response.json()
                if search_data.get("results"):
                    parent_page_id = search_data["results"][0]["id"]
            
            # If no existing page found, create a container page first
            if not parent_page_id:
                page_response = requests.post(
                    "https://api.notion.com/v1/pages",
                    headers=headers,
                    json={
                        "parent": {"type": "page_id", "page_id": ""},
                        "properties": {
                            "title": {
                                "title": [{"text": {"content": "Notepad++ Migration Container"}}]
                            }
                        }
                    }
                )
                
                if page_response.status_code != 200:
                    # Try workspace as parent
                    workspace_response = requests.post(
                        "https://api.notion.com/v1/pages",
                        headers=headers,
                        json={
                            "parent": {"type": "workspace", "workspace": True},
                            "properties": {
                                "title": {
                                    "title": [{"text": {"content": "Notepad++ Migration Container"}}]
                                }
                            }
                        }
                    )
                    
                    if workspace_response.status_code == 200:
                        parent_page_id = workspace_response.json()["id"]
                else:
                    parent_page_id = page_response.json()["id"]
            
            if not parent_page_id:
                return None
                
            # Create database
            database_payload = {
                "parent": {"page_id": parent_page_id},
                "title": [{"text": {"content": "Notepad++ Notes"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Source File": {"rich_text": {}},
                    "Import Date": {"date": {}},
                    "Content Type": {"select": {
                        "options": [
                            {"name": "Text", "color": "blue"},
                            {"name": "Code", "color": "green"},
                            {"name": "Script", "color": "orange"},
                            {"name": "Other", "color": "gray"}
                        ]
                    }}
                }
            }
            
            db_response = requests.post(
                "https://api.notion.com/v1/databases",
                headers=headers,
                json=database_payload
            )
            
            if db_response.status_code == 200:
                return db_response.json()["id"]
                
        except Exception as e:
            print(f"Error creating database: {e}")
            
        return None
    
    def migrate_notes(self):
        """Migrate notes to Notion"""
        headers = {
            "Authorization": f"Bearer {self.notion_token.get()}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
        
        successful = 0
        failed = 0
        
        # Determine where to create pages
        database_id = None
        db_id_input = self.notion_database_id.get().strip()
        
        # Check if we have a valid database ID
        if db_id_input and len(db_id_input) >= 32:
            clean_id = db_id_input.replace('-', '').replace('_', '')
            if len(clean_id) == 32:
                database_id = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"
        
        # If no valid database ID, create a new database
        if not database_id:
            self.root.after(0, lambda: self.status_label.config(text="Creating new database..."))
            database_id = self.create_database(headers)
            
            if database_id:
                self.root.after(0, lambda: self.status_label.config(text="Database created successfully!"))
                # Save the new database ID
                self.notion_database_id.set(database_id)
                self.save_config()
            else:
                self.root.after(0, lambda: self.status_label.config(text="Failed to create database"))
                return
        
        for i, note in enumerate(self.notes_data):
            try:
                self.root.after(0, lambda i=i: self.progress.config(value=i))
                self.root.after(0, lambda note=note: self.status_label.config(
                    text=f"Migrating: {note['name']}..."
                ))
                
                # Determine content type based on file extension
                file_ext = os.path.splitext(note['name'])[1].lower()
                content_type = "Code" if file_ext in ['.py', '.js', '.html', '.css', '.xml', '.sh'] else "Text"
                
                # Create page payload for database
                page_data = {
                    "parent": {"database_id": database_id},
                    "properties": {
                        "Name": {
                            "title": [{"text": {"content": note['name']}}]
                        },
                        "Source File": {
                            "rich_text": [{"text": {"content": note['path']}}]
                        },
                        "Import Date": {
                            "date": {"start": time.strftime("%Y-%m-%d")}
                        },
                        "Content Type": {
                            "select": {"name": content_type}
                        }
                    },
                    "children": []
                }
                
                # Add content as blocks
                if note['content']:
                    # Split content into manageable chunks
                    content_chunks = self.split_content(note['content'], 1900)  # Leave room for formatting
                    
                    for chunk in content_chunks[:20]:  # Limit to first 20 chunks
                        if chunk.strip():
                            if content_type == "Code":
                                page_data["children"].append({
                                    "object": "block",
                                    "type": "code",
                                    "code": {
                                        "rich_text": [{"type": "text", "text": {"content": chunk}}],
                                        "language": self.get_language_from_extension(file_ext)
                                    }
                                })
                            else:
                                page_data["children"].append({
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                                    }
                                })
                
                # Make API request
                response = requests.post("https://api.notion.com/v1/pages", 
                                       headers=headers, 
                                       json=page_data)
                
                if response.status_code == 200:
                    successful += 1
                    status = "✓ Migrated"
                else:
                    failed += 1
                    status = "✗ Failed"
                    print(f"Failed to create page for {note['name']}: {response.text}")
                
                # Update tree view
                item_id = self.notes_tree.get_children()[i]
                current_values = list(self.notes_tree.item(item_id)['values'])
                current_values[3] = status
                self.root.after(0, lambda item=item_id, values=current_values: 
                               self.notes_tree.item(item, values=values))
                
                time.sleep(0.1)  # Rate limiting
                
            except Exception as e:
                failed += 1
                print(f"Error migrating {note['name']}: {str(e)}")
        
        self.root.after(0, lambda: self.progress.config(value=len(self.notes_data)))
        self.root.after(0, lambda: self.status_label.config(
            text=f"Migration complete! {successful} successful, {failed} failed"
        ))
        
        if successful > 0:
            message = f"Successfully migrated {successful} notes to Notion!"
            if database_id:
                message += f"\n\nDatabase ID: {database_id}\n(This has been saved for future use)"
            
            self.root.after(0, lambda: messagebox.showinfo("Migration Complete", message))
    
    def split_content(self, content, max_length):
        """Split content into chunks of specified max length"""
        chunks = []
        lines = content.split('\n')
        current_chunk = ""
        
        for line in lines:
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.rstrip())
                current_chunk = line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.rstrip())
            
        return chunks
    
    def get_language_from_extension(self, ext):
        """Get code language from file extension"""
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.html': 'html',
            '.css': 'css',
            '.xml': 'xml',
            '.sh': 'shell',
            '.bat': 'batch',
            '.ps1': 'powershell',
            '.sql': 'sql',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml'
        }
        return language_map.get(ext, 'plain text')
    
    def migration_complete(self):
        """Re-enable buttons after migration"""
        self.migrate_btn.config(state="normal")
        self.scan_btn.config(state="normal")
        self.test_btn.config(state="normal")
    
    def load_config(self):
        """Load saved configuration from file"""
        try:
            if os.path.exists(self.config_file):
                config = configparser.ConfigParser()
                config.read(self.config_file)
                
                if 'Notion' in config:
                    # Decrypt/decode the token (simple base64 for basic obfuscation)
                    import base64
                    token = config.get('Notion', 'token', fallback='')
                    if token:
                        try:
                            decoded_token = base64.b64decode(token.encode()).decode()
                            self.notion_token.set(decoded_token)
                        except:
                            pass  # If decoding fails, just leave empty
                    
                    database_id = config.get('Notion', 'database_id', fallback='')
                    self.notion_database_id.set(database_id)
                    
        except Exception as e:
            # If config loading fails, just continue with empty values
            pass
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            config = configparser.ConfigParser()
            
            # Create Notion section
            config.add_section('Notion')
            
            # Encrypt/encode the token (simple base64 for basic obfuscation)
            import base64
            token = self.notion_token.get()
            if token:
                encoded_token = base64.b64encode(token.encode()).decode()
                config.set('Notion', 'token', encoded_token)
            
            config.set('Notion', 'database_id', self.notion_database_id.get())
            
            # Write to file
            with open(self.config_file, 'w') as f:
                config.write(f)
            
            messagebox.showinfo("Configuration Saved", "Your settings have been saved successfully!")
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save configuration: {str(e)}")
    
    def toggle_token_visibility(self):
        """Toggle between showing and hiding the token"""
        if self.show_token.get():
            self.token_entry.config(show="")
        else:
            self.token_entry.config(show="*")

def main():
    root = tk.Tk()
    app = NotepadNotionMigrator(root)
    root.mainloop()

if __name__ == "__main__":
    main()
