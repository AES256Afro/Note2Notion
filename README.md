# Notepad++ to Notion Migrator

A Python GUI application that migrates all active Notepad++ tabs to Notion pages automatically.

## Features
- Scans active Notepad++ tabs and backup files
- Creates an organized Notion database with metadata
- Supports code syntax highlighting
- Persistent configuration storage
- Progress tracking and error handling

## Prerequisites
- Python 3.7+
- Notion integration token
- Active Notepad++ installation

## Installation
1. Clone this repository
2. Install dependencies: `pip install requests`
3. Run: `python notepad_notion_migrator.py`

## Setup
1. Create a Notion integration at https://www.notion.so/my-integrations
2. Copy your integration token
3. (Optional) Create a database in Notion and copy its ID
4. Run the application and enter your credentials

## Usage
1. Open files in Notepad++
2. Launch the migrator
3. Click "Scan Notepad++ Tabs"
4. Test your Notion connection
5. Click "Migrate to Notion"

## License
MIT License
