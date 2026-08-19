"""Update an existing winget-pkgs PR with the latest manifest files.

Usage:
    WINGET_PAT=<token> python tools/update_winget_pr.py
    WINGET_PAT=<token> python tools/update_winget_pr.py --dry-run

This script:
1. Uses the GitHub API to discover the PR head branch name
2. Fetches that branch from the fork
3. Replaces the manifest files with our local versions
4. Pushes the changes back to update the PR

Requirements:
    - Set WINGET_PAT environment variable with a GitHub PAT (public_repo scope)
    - The PR must already exist on microsoft/winget-pkgs
    - git and curl must be on PATH
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
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


def _mask(text: str, secret: str) -> str:
    """Replace a secret in text with *** for safe logging."""
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def run(cmd: list[str], *, cwd: str | None = None, secret: str = "") -> subprocess.CompletedProcess:
    print(f"  $ {_mask(' '.join(cmd), secret)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout.strip():
            print(f"    stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()}")
    return result


def require(cmd: list[str], *, cwd: str | None = None, secret: str = "") -> subprocess.CompletedProcess:
    result = run(cmd, cwd=cwd, secret=secret)
    if result.returncode != 0:
        raise ScriptError(f"command failed: {_mask(' '.join(cmd), secret)}")
    return result


def get_pr_head_branch(pr_number: int, token: str) -> str:
    """Use the GitHub REST API to discover the head branch name of a PR."""
    url = f"https://api.github.com/repos/microsoft/winget-pkgs/pulls/{pr_number}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            head = data["head"]
            return head["ref"]  # e.g. "AetherisProject.AetherisWindowsInstaller-1.0.0-..."
    except Exception as exc:
        raise ScriptError(f"could not fetch PR #{pr_number} metadata via API: {exc}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Update winget-pkgs PR with latest manifests")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args(argv)

    token = os.environ.get("WINGET_PAT", "").strip()
    if not token and not args.dry_run:
        print("error: WINGET_PAT environment variable is not set", file=sys.stderr)
        print("  export WINGET_PAT=<your-github-pat>", file=sys.stderr)
        return 1

    manifest_files = sorted(MANIFEST_DIR.glob("*.yaml"))
    if not manifest_files:
        print("error: no manifest files found in winget/", file=sys.stderr)
        return 1
    print(f"Found {len(manifest_files)} local manifests:")
    for f in manifest_files:
        print(f"  {f.name}")

    with tempfile.TemporaryDirectory(prefix="winget-pkgs-") as tmpdir:
        clone_dir = Path(tmpdir) / "winget-pkgs"

        if args.dry_run:
            print(f"\n[dry-run] would query GitHub API for PR #{PR_NUMBER} head branch")
            print(f"[dry-run] would clone {UPSTREAM_REPO}")
            print(f"[dry-run] would fetch and check out the PR branch from {FORK_OWNER}'s fork")
            print(f"[dry-run] would copy manifests to manifests/{MANIFEST_PARTITION}/AetherisProject/AetherisWindowsInstaller/{VERSION}/")
            for f in manifest_files:
                print(f"  {f.name}")
            print("[dry-run] would commit and push")
            print(f"\nDone! (dry-run)")
            return 0

        try:
            # Step 1: discover the PR head branch name via GitHub API
            print(f"\nQuerying GitHub API for PR #{PR_NUMBER} head branch...")
            head_branch = get_pr_head_branch(PR_NUMBER, token)
            print(f"  PR head branch: {head_branch}")

            # Step 2: clone the upstream repo
            print(f"\nCloning {UPSTREAM_REPO} (shallow)...")
            require(["git", "clone", "--depth", "1", UPSTREAM_REPO, str(clone_dir)], secret=token)

            # Step 3: fetch the PR head from the fork
            fork_url = f"https://github.com/{FORK_OWNER}/winget-pkgs.git"
            print(f"\nFetching branch '{head_branch}' from {FORK_OWNER}'s fork...")
            require(
                ["git", "fetch", "--depth", "1", fork_url, head_branch],
                cwd=str(clone_dir),
                secret=token,
            )

            # Step 4: check out the branch
            print(f"Checking out '{head_branch}'...")
            require(["git", "checkout", "FETCH_HEAD"], cwd=str(clone_dir), secret=token)

            # Step 5: configure git
            require(["git", "config", "user.name", "github-actions[bot]"], cwd=str(clone_dir), secret=token)
            require(
                ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
                cwd=str(clone_dir),
                secret=token,
            )

            # Step 6: set remote with auth
            auth_url = f"https://{token}@github.com/{FORK_OWNER}/winget-pkgs.git"
            require(["git", "remote", "set-url", "origin", auth_url], cwd=str(clone_dir), secret=token)

            # Step 7: copy manifests
            repo_manifest_dir = (
                clone_dir / "manifests" / MANIFEST_PARTITION
                / "AetherisProject" / "AetherisWindowsInstaller" / VERSION
            )
            repo_manifest_dir.mkdir(parents=True, exist_ok=True)

            print(f"\nCopying manifests to {repo_manifest_dir.relative_to(clone_dir)}...")
            for f in manifest_files:
                shutil.copy2(f, repo_manifest_dir / f.name)
                print(f"  {f.name}")

            # Step 8: stage, commit, push
            print("\nCommitting changes...")
            require(["git", "add", "-A"], cwd=str(clone_dir), secret=token)
            require(
                [
                    "git", "commit", "-m",
                    f"Update {PACKAGE_ID} {VERSION} manifests\n\n"
                    "Update InstallerSha256, InstallerType (exe), Dependencies\n"
                    "(Docker + Git), ManifestVersion (1.12.0), and metadata.",
                ],
                cwd=str(clone_dir),
                secret=token,
            )

            print(f"\nPushing to {FORK_OWNER}/winget-pkgs:{head_branch}...")
            result = run(
                ["git", "push", "origin", f"HEAD:{head_branch}"],
                cwd=str(clone_dir),
                secret=token,
            )
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
