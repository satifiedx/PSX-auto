@echo off
rem Builds dist\PSX-auto.exe
pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --onefile --noconsole --name PSX-auto --add-data "bin;bin" main.py
