"""Update an existing winget-pkgs PR with the latest manifest files.

Usage:
    WINGET_PAT=<token> python tools/update_winget_pr.py
    WINGET_PAT=<token> python tools/update_winget_pr.py --dry-run

This script:
1. Clones microsoft/winget-pkgs (shallow)
2. Fetches the PR branch from the upstream PR
3. Replaces the manifest files with our local versions
4. Pushes the changes back to update the PR

Requirements:
    - Set WINGET_PAT environment variable with a GitHub PAT (public_repo scope)
    - The PR must already exist on microsoft/winget-pkgs

The PR branch is auto-detected via git fetch origin pull/<number>/head.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "winget"
PR_NUMBER = 420938
UPSTREAM_REPO = "https://github.com/microsoft/winget-pkgs.git"
FORK_OWNER = "Leo-Galli"
PACKAGE_ID = "AetherisProject.AetherisWindowsInstaller"
VERSION = "1.0.0"
MANIFEST_PARTITION = "a"  # AetherisProject starts with 'a'


class ScriptError(Exception):
    """Raised when a step fails."""


def _mask_token(text: str, token: str) -> str:
    """Replace the token in a string with *** for safe logging."""
    if token and token in text:
        return text.replace(token, "***")
    return text


def run(cmd: list[str], *, cwd: str | None = None, token: str = "") -> subprocess.CompletedProcess:
    print(f"  $ {_mask_token(' '.join(cmd), token)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout.strip():
            print(f"    stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()}")
    return result


def require_run(cmd: list[str], *, cwd: str | None = None, token: str = "") -> subprocess.CompletedProcess:
    result = run(cmd, cwd=cwd, token=token)
    if result.returncode != 0:
        raise ScriptError(f"command failed: {_mask_token(' '.join(cmd), token)}")
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Update winget-pkgs PR with latest manifests")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args(argv)

    # Read token from environment
    token = os.environ.get("WINGET_PAT", "").strip()
    if not token and not args.dry_run:
        print("error: WINGET_PAT environment variable is not set", file=sys.stderr)
        print("  export WINGET_PAT=<your-github-pat>", file=sys.stderr)
        return 1

    # Validate local manifests exist
    manifest_files = sorted(MANIFEST_DIR.glob("*.yaml"))
    if not manifest_files:
        print("error: no manifest files found in winget/", file=sys.stderr)
        return 1
    print(f"Found {len(manifest_files)} local manifests:")
    for f in manifest_files:
        print(f"  {f.name}")

    # Create a temporary directory for the clone
    with tempfile.TemporaryDirectory(prefix="winget-pkgs-") as tmpdir:
        clone_dir = Path(tmpdir) / "winget-pkgs"

        if args.dry_run:
            print(f"\n[dry-run] would clone {UPSTREAM_REPO}")
            print(f"[dry-run] would fetch PR #{PR_NUMBER} branch")
            print(f"[dry-run] would copy manifests to manifests/{MANIFEST_PARTITION}/AetherisProject/AetherisWindowsInstaller/{VERSION}/")
            for f in manifest_files:
                print(f"  {f.name}")
            print("[dry-run] would commit and push")
        else:
            try:
                print(f"\nCloning {UPSTREAM_REPO} (shallow)...")
                require_run(["git", "clone", "--depth", "1", UPSTREAM_REPO, str(clone_dir)], token=token)

                # Fetch the PR branch
                print(f"\nFetching PR #{PR_NUMBER} branch...")
                result = run(
                    ["git", "fetch", "origin", f"pull/{PR_NUMBER}/head:pr-{PR_NUMBER}"],
                    cwd=str(clone_dir),
                    token=token,
                )
                if result.returncode != 0:
                    raise ScriptError(f"could not fetch PR #{PR_NUMBER} branch")

                branch = f"pr-{PR_NUMBER}"
                print(f"  Found branch: {branch}")

                # Check out the PR branch
                print(f"Checking out {branch}...")
                require_run(["git", "checkout", branch], cwd=str(clone_dir), token=token)

                # Configure git for commit
                require_run(["git", "config", "user.name", "github-actions[bot]"], cwd=str(clone_dir), token=token)
                require_run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=str(clone_dir), token=token)

                # Set up the remote with auth for push
                auth_url = f"https://{token}@github.com/{FORK_OWNER}/winget-pkgs.git"
                require_run(["git", "remote", "set-url", "origin", auth_url], cwd=str(clone_dir), token=token)

                # Determine the manifest path in the repo
                repo_manifest_dir = clone_dir / "manifests" / MANIFEST_PARTITION / "AetherisProject" / "AetherisWindowsInstaller" / VERSION
                repo_manifest_dir.mkdir(parents=True, exist_ok=True)

                # Copy each manifest file
                print(f"\nCopying manifests to {repo_manifest_dir.relative_to(clone_dir)}...")
                for f in manifest_files:
                    dest = repo_manifest_dir / f.name
                    shutil.copy2(f, dest)
                    print(f"  {f.name}")

                # Stage and commit
                print("\nCommitting changes...")
                require_run(["git", "add", "-A"], cwd=str(clone_dir), token=token)
                require_run(
                    ["git", "commit", "-m", f"Update {PACKAGE_ID} {VERSION} manifests\n\nUpdate InstallerSha256, InstallerType (exe), Dependencies\n(Docker + Git), ManifestVersion (1.12.0), and metadata."],
                    cwd=str(clone_dir),
                    token=token,
                )

                # Push
                print("\nPushing to fork...")
                result = run(["git", "push", "origin", branch], cwd=str(clone_dir), token=token)
                if result.returncode != 0:
                    raise ScriptError("push failed — check your WINGET_PAT has 'public_repo' scope")

            except ScriptError as exc:
                print(f"\nerror: {exc}", file=sys.stderr)
                return 1

    print(f"\nDone! PR #{PR_NUMBER} should now show the updated manifests.")
    print(f"  https://github.com/microsoft/winget-pkgs/pull/{PR_NUMBER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
