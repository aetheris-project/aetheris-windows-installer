"""One-off fix for the winget-pkgs PR branch.

The PR originally added the manifests under the split location
    manifests/a/AetherisProject/AetherisWindowsInstaller/1.0.0/
Later API-driven hash updates accidentally created a duplicate manifest at
the flat location
    manifests/a/AetherisProject.AetherisWindowsInstaller/1.0.0/
which breaks winget's process-pr (Internal-Error-PR).

This script:
  1. deletes the stray flat-path installer.yaml from the fork branch,
  2. updates the split-path installer.yaml with CRLF line endings and the
     new SHA256 hash.

It talks to the GitHub API with the gh auth token, so no clone is needed.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.request

FORK = "Leo-Galli/winget-pkgs"
BRANCH = "AetherisProject.AetherisWindowsInstaller-1.0.0"
SPLIT_YAML = "manifests/a/AetherisProject/AetherisWindowsInstaller/1.0.0/AetherisProject.AetherisWindowsInstaller.installer.yaml"
FLAT_YAML = "manifests/a/AetherisProject.AetherisWindowsInstaller/1.0.0/AetherisProject.AetherisWindowsInstaller.installer.yaml"
NEW_HASH = "581bcfa41e6b3e00238c961c054d70a0b5fcf05d3471803f56eb73e3139080ee"

API = "https://api.github.com"


def token() -> str:
    out = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    return out


def api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "aetheris-fix-winget")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {body}") from exc


def main() -> int:
    # --- 1. Delete the stray flat-path manifest ---------------------------
    flat = api(
        f"/repos/{FORK}/contents/{FLAT_YAML}?ref={BRANCH}",
    )
    flat_sha = flat["sha"]
    print(f"flat manifest sha: {flat_sha}")
    api(
        f"/repos/{FORK}/contents/{FLAT_YAML}",
        method="DELETE",
        payload={"message": "Remove duplicate manifest from flat path", "branch": BRANCH, "sha": flat_sha},
    )
    print("deleted flat-path duplicate manifest")

    # --- 2. Update the split-path installer.yaml (CRLF + new hash) --------
    split = api(f"/repos/{FORK}/contents/{SPLIT_YAML}?ref={BRANCH}")
    split_sha = split["sha"]
    content = base64.b64decode(split["content"]).decode("utf-8")
    old_hash = content.split("InstallerSha256: ", 1)[1].splitlines()[0].strip()
    print(f"split manifest sha: {split_sha}, current hash: {old_hash}")

    content = content.replace(old_hash, NEW_HASH)
    # Normalize to CRLF, as winget-pkgs requires for manifest files.
    content = content.replace("\r\n", "\n").replace("\n", "\r\n")
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    api(
        f"/repos/{FORK}/contents/{SPLIT_YAML}",
        method="PUT",
        payload={
            "message": "Update InstallerSha256 for AetherisProject.AetherisWindowsInstaller 1.0.0",
            "branch": BRANCH,
            "sha": split_sha,
            "content": encoded,
        },
    )
    print(f"updated split manifest to {NEW_HASH} (CRLF)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
