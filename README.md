# Note2Notion
Tool that migrates saved and active tabs in NotePad++ and migrates that data to Notion.io

Key Features
📋 Tab Detection:

Scans Notepad++ session files to find currently open tabs
Also checks backup/temp files for unsaved work
Handles multiple encoding types (UTF-8, UTF-16, etc.)

🔗 Notion Integration:

Connects to Notion API with your integration token
Creates new pages for each note
Preserves content formatting and adds source information
Option to migrate to a specific database or your workspace

👀 Preview & Control:

Shows all detected notes before migration
Displays file names, paths, sizes, and status
Progress tracking during migration
Success/failure status for each note

⚙️ User-Friendly Interface:

Simple GUI with clear steps
Test connection functionality
Confirmation before migration
Real-time progress updates

Setup Instructions

Install Required Dependencies:
bashpip install requests tkinter

Set Up Notion Integration:

Go to https://www.notion.so/my-integrations
Create a new integration and copy the token
Optionally, create a database for your notes and get its ID


Run the Application:

Save the code as notepad_notion_migrator.py
Run with python notepad_notion_migrator.py



How to Use

Configure Notion: Enter your integration token (and optionally database ID)
Test Connection: Verify your Notion API access
Scan Tabs: Detect all active Notepad++ tabs
Review Notes: Check the preview to see what will be migrated
Migrate: Click to start the migration process

The tool will create individual Notion pages for each note, preserving the content and adding metadata about the original file location. Would you like me to modify anything about how it works or add any additional features?
