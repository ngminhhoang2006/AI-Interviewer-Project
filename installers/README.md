# AI Interviewer installers

Each installer clones the project from GitHub, builds a Python virtual environment,
and adds a launcher to your system. Pick the folder for your operating system.

| OS      | Install                         | Uninstall                         |
|---------|---------------------------------|-----------------------------------|
| Linux   | `bash linux/install.sh`         | `bash linux/uninstall.sh`         |
| macOS   | double-click `macos/install_macos.command`   | double-click `macos/uninstall_macos.command`   |
| Windows | double-click `windows/install_windows.bat`   | double-click `windows/uninstall_windows.bat`   |

Notes
- Keep the `.bat` and `.ps1` files together in the same folder (the `.bat` calls the `.ps1`).
- Config (SECRET_KEY, email settings) is stored outside the project so updates don't overwrite it:
  Linux/macOS `~/.config/ai-interviewer/env`, Windows `%APPDATA%\ai-interviewer\env`.
- Uninstall offers to back up candidate uploads and the accounts database first.
- Ollama and the `qwen3:8b` model are installed/pulled by the installer if you agree.
