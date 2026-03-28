#!/bin/zsh
cd "$HOME/Desktop/文献管理html"
python3 scripts/update_library.py
python3 scripts/start_library_server.py
