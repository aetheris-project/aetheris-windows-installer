<p align="center">
  <img src="../.github/assets/icon.svg" onerror="this.src='https://raw.githubusercontent.com/aetheris-project/aetheris-windows-installer/main/.github/assets/icon.svg'" alt="Aetheris Windows Installer" width="88" style="filter: drop-shadow(0 0 20px rgba(16,185,129,0.5))">
</p>

<h1 align="center">Aetheris — Windows Installer</h1>

<p align="center">
  <strong>Interactive TUI installer for the Aetheris control panel on Windows</strong>
</p>

<p align="center">
  <a href="https://github.com/aetheris-project/aetheris-windows-installer/releases"><img src="https://img.shields.io/badge/Download-Latest%20Release-10B981?style=for-the-badge&logo=github&logoColor=white" alt="Download"></a>
  <a href="https://aetheris-docs.vercel.app/wiki/windows-installer"><img src="https://img.shields.io/badge/Docs-Windows%20Guide-0EA5E9?style=for-the-badge&logo=readme" alt="Docs"></a>
  <a href="https://discord.gg/6GcfebuT2A"><img src="https://img.shields.io/badge/Discord-Help-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D4?style=flat-square&logo=windows" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/winget-Package-2ea44f?style=flat-square" alt="winget">
  <img src="https://img.shields.io/badge/Docker-Desktop-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Desktop">
  <img src="https://img.shields.io/badge/TUI-Curses-18181B?style=flat-square" alt="Curses TUI">
  <img src="https://img.shields.io/badge/Tests-Passing-10B981?style=flat-square" alt="Tests">
</p>

---

<br>

> Interactive installer for the **Aetheris billing & virtualization control
> panel** on **Windows 10/11 64-bit**. The platform runs as a Docker stack
> (web, worker, backend, PostgreSQL, Redis). This installer manages the
> environment around it: installing dependencies via winget, cloning and
> starting the stack, managing it from a live TUI menu — or tearing it
> cleanly back down.

<br>

## ✨ Features

<table>
  <tr>
    <td width="50%" align="left">
      <h3>🎮 Interactive TUI wizard</h3>
      <ul>
        <li>Arrow-key navigation · <kbd>Space</kbd> toggles · <kbd>Enter</kbd> confirms</li>
        <li>Box-drawing frames · brand accent colors · live spinner</li>
        <li>Emoji-free by design</li>
        <li>Falls back to plain prompts when <code>windows-curses</code> is unavailable</li>
      </ul>
    </td>
    <td width="50%" align="left">
      <h3>📦 Dependency management</h3>
      <ul>
        <li>Installs <strong>Docker Desktop</strong>, <strong>Git for Windows</strong> via winget</li>
        <li>Optional: Node.js LTS · Python 3.12</li>
        <li>Dependencies toggled in the wizard or CLI</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td align="left">
      <h3>🛠️ Full stack deployment</h3>
      <ul>
        <li>Clones <code>aetheris-app</code> into your chosen directory</li>
        <li>Runs <code>docker compose up -d --build</code></li>
        <li>Choose <strong>PostgreSQL container</strong> or <strong>local SQLite .db</strong></li>
        <li>Decide when <code>.env</code> is written: now or later (manual)</li>
      </ul>
    </td>
    <td align="left">
      <h3>🧹 Lifecycle control</h3>
      <ul>
        <li><strong>Uninstall</strong>: <code>docker compose down -v</code> + remove directory</li>
        <li><strong>Dry-run</strong>: preview every command, execute nothing</li>
        <li><strong>Manage</strong> menu: status · start · stop · live logs viewer</li>
        <li><strong>Auto-updater</strong>: checks GitHub Releases on launch</li>
      </ul>
    </td>
  </tr>
</table>

<br>

## 📦 Requirements

| Component | Minimum |
|---|---|
| **OS** | Windows 10 / 11 — **64-bit** |
| **RAM** | **4 GB** or more (Docker Desktop) |
| **Disk** | 10 GB free recommended |
| **Architecture** | x86-64 · ARM64 via emulation |

<br>

## ⬇️ Download

### Method 1 — winget (recommended, auto-updates)

```powershell
winget install AetherisProject.AetherisWindowsInstaller
```

Winget installs Docker Desktop and Git for Windows automatically as declared
dependencies.

### Method 2 — curl (CMD / PowerShell / Git Bash)

```cmd
curl -L -o aetheris-windows-installer.exe ^
  https://github.com/aetheris-project/aetheris-windows-installer/releases/latest/download/aetheris-windows-installer.exe
```

### Method 3 — PowerShell Invoke-WebRequest

```powershell
Invoke-WebRequest -Uri https://github.com/aetheris-project/aetheris-windows-installer/releases/latest/download/aetheris-windows-installer.exe -OutFile aetheris-windows-installer.exe
```

### Verify (optional)

```cmd
certutil -hashfile aetheris-windows-installer.exe SHA256
```

Compare with the hash in the [winget manifest](winget/AetherisProject.AetherisWindowsInstaller.installer.yaml).

<br>

## 🎮 Usage

### Interactive (double-click the .exe)

```
aetheris-windows-installer
```

- <kbd>↑</kbd><kbd>↓</kbd> / <kbd>j</kbd><kbd>k</kbd> — navigate
- <kbd>Space</kbd> — toggle dependency checkboxes
- <kbd>Enter</kbd> — confirm
- <kbd>Esc</kbd> — go back one step
- <kbd>q</kbd> — quit

### Command line

```powershell
# Only install dependencies (Docker Desktop + Git)
aetheris-windows-installer --deps

# Only deploy the software stack
aetheris-windows-installer --software

# Install everything
aetheris-windows-installer --both

# Uninstall (stops stack + removes directory)
aetheris-windows-installer --uninstall

# Custom target directory (default: %USERPROFILE%\aetheris)
aetheris-windows-installer --both --dir "D:\Aetheris"

# Use local SQLite .db instead of the PostgreSQL container
aetheris-windows-installer --both --db sqlite

# Skip writing the .env file (you will create it manually)
aetheris-windows-installer --software --no-env

# Preview actions without executing anything
aetheris-windows-installer --both --dry-run
```

### From source

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[tui,dev]"
python -m aetheris_wininstaller
```

> The TUI requires `windows-curses`; it's pulled in via the `tui` extra and
> bundled into the standalone executable by `tools/build_exe.py`.

<br>

## 📋 Installed Dependencies

| Dependency | winget ID | Required |
|---|---|---|
| Docker Desktop | `Docker.DockerDesktop` | ✅ Yes |
| Git for Windows | `Git.Git` | ✅ Yes |
| Node.js LTS | `OpenJS.NodeJS.LTS` | ❌ Optional |
| Python 3.12 | `Python.Python.3.12` | ❌ Optional |

Docker and Git are always required and cannot be deselected. Optional
dependencies are toggled in the wizard or via CLI flags.

<br>

## 🎯 After Installation

The stack is up at:
- **Web UI**: http://localhost:3000
- **Backend health**: http://localhost:8000/health

Two database modes are supported:

| Mode | What happens |
|---|---|
| **PostgreSQL** (default) | Starts a PostgreSQL container. A random `POSTGRES_PASSWORD` is generated. |
| **SQLite** (recommended for tests) | No DB container. Uses `docker-compose.sqlite.yml` and stores data in a local `.db` file. The installer sets `AETHERIS_DB_MODE=sqlite` for you. |

The project lives in the directory you chose (default
`%USERPROFILE%\aetheris`) under `aetheris-app`. A random
`AETHERIS_SECRET` is generated on first install.

---

<p align="center">
  <strong>Made with 💚 by <a href="https://github.com/Leo-Galli">Leonardo Galli</a></strong>
</p>

<p align="center">
  <a href="https://github.com/aetheris-project/aetheris-installer">Cross-platform installer</a>
  ·
  <a href="https://github.com/aetheris-project/aetheris-app">App</a>
  ·
  <a href="https://github.com/aetheris-project/aetheris-docs">Docs</a>
  ·
  <a href="https://discord.gg/6GcfebuT2A">Discord</a>
  ·
  <a href="https://paypal.me/LeonardoGalliITA">Donate</a>
</p>

## 📄 License

Licensed under **GNU Affero General Public License v3.0 (AGPL-3.0)**.
See [LICENSE.md](LICENSE.md).
