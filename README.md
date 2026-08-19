# Aetheris Windows Installer

Interactive installer for the [Aetheris control plane](https://github.com/aetheris-project/aetheris-app) on Windows.

The platform runs as a Docker stack (web, worker, backend, PostgreSQL, Redis). This installer manages everything around it: it can install the required dependencies through winget, clone and start the stack, or tear it all down again.

## Features

- Interactive TUI wizard with arrow-key navigation, archinstall-style (no emoji)
- Dependency management through winget (Docker Desktop, Git for Windows, Node.js LTS, Python 3.12)
- Software install: clones `aetheris-app` and runs `docker compose up -d --build`
- Uninstall: stops the stack, removes volumes and the application directory
- Dry-run mode to preview every command without executing it
- Plain-text fallback UI when the curses module is not available

## Requirements

- Windows 10/11, 64-bit
- 4 GB RAM or more (Docker Desktop needs it)

## Usage

### Interactive wizard (recommended)

Double-click `aetheris-windows-installer.exe` or run:

```
aetheris-windows-installer
```

Use the arrow keys (or j/k) to move, Space to toggle dependencies, Enter to confirm, q to quit.

### Command line

```
# Install dependencies only (Docker Desktop, Git for Windows)
aetheris-windows-installer --deps

# Install the software stack only (clone + docker compose up -d --build)
aetheris-windows-installer --software

# Install everything
aetheris-windows-installer --both

# Stop the stack and remove the application directory
aetheris-windows-installer --uninstall

# Preview what would run, without executing anything
aetheris-windows-installer --both --dry-run
```

### From source

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[tui,dev]"
python -m aetheris_wininstaller
```

On Windows the TUI requires the `windows-curses` package; it is pulled in by the `tui` extra and bundled into the standalone executable.

## What it installs

| Dependency | winget id | Required |
| --- | --- | --- |
| Docker Desktop | `Docker.DockerDesktop` | yes |
| Git for Windows | `Git.Git` | yes |
| Node.js LTS | `OpenJS.NodeJS.LTS` | no |
| Python 3.12 | `Python.Python.3.12` | no |

Optional dependencies can be toggled in the wizard. Docker Desktop and Git are always required and cannot be deselected.

## After installation

The stack is available at:

- Web UI: http://localhost:3000
- Backend health: http://localhost:8000/health

The application lives in `%USERPROFILE%\aetheris\aetheris-app` with its `.env` next to the compose file. A random `AETHERIS_SECRET` is generated on first install.

## Development

```
pip install -e ".[dev]"
python -m pytest -q
python tools/build_exe.py   # produces dist\aetheris-windows-installer.exe
```

## License

Proprietary. See the Aetheris Project organization for the full picture.
