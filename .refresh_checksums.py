#!/usr/bin/env python3
"""Refresh SHA-256 checksums for pinned external dependencies.

Reads .pinned_versions.yml, fetches checksums from upstream APIs, and
writes the results back. Covers Packer binary, pip packages, Packer
plugins, and Ansible Galaxy collections.

PowerSTIG and NuGet hashes require a Windows environment and are not
handled by this script; they must be updated manually.

Usage:
    python .refresh_checksums.py             # fetch + write checksums
    python .refresh_checksums.py --check     # exit 1 if any checksum changed
    python .refresh_checksums.py --dry-run   # print what would change
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML is required. Install it with: pip install pyyaml\n"
        "(It is already installed if Ansible is installed.)"
    )

SCRIPT_DIR = Path(__file__).resolve().parent
VERSIONS_FILE = SCRIPT_DIR / ".pinned_versions.yml"

HASHICORP_RELEASES = "https://releases.hashicorp.com"
HASHICORP_API = "https://api.releases.hashicorp.com/v1/releases"
PYPI_API = "https://pypi.org/pypi"
GALAXY_API = (
    "https://galaxy.ansible.com/api/v3/plugin/ansible"
    "/content/published/collections/index"
)


def _fetch(url: str) -> str:
    """Fetch a URL and return its body as a string."""
    req = urllib.request.Request(url, headers={"User-Agent": "refresh-checksums/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def _fetch_json(url: str) -> dict | list:
    """Fetch a URL and parse the response as JSON."""
    return json.loads(_fetch(url))


def fetch_packer_sha256(version: str, platform: str) -> str:
    """Fetch the SHA-256 for a Packer binary from HashiCorp releases."""
    url = f"{HASHICORP_RELEASES}/packer/{version}/packer_{version}_SHA256SUMS"
    body = _fetch(url)
    needle = f"packer_{version}_{platform}.zip"
    for line in body.splitlines():
        if needle in line:
            return line.split()[0]
    sys.exit(f"Could not find {needle} in SHA256SUMS for Packer {version}")


def fetch_pip_sha256(name: str, version: str) -> str:
    """Fetch the SHA-256 for a pip package wheel (or sdist) from PyPI."""
    url = f"{PYPI_API}/{name}/{version}/json"
    data = _fetch_json(url)
    for entry in data.get("urls", []):
        if entry.get("packagetype") == "bdist_wheel":
            return entry["digests"]["sha256"]
    for entry in data.get("urls", []):
        if entry.get("packagetype") == "sdist":
            return entry["digests"]["sha256"]
    sys.exit(f"No wheel or sdist found on PyPI for {name}=={version}")


def fetch_packer_plugin_latest(plugin_name: str) -> str:
    """Fetch the latest stable version of a Packer plugin from the HashiCorp API."""
    url = f"{HASHICORP_API}/packer-plugin-{plugin_name}?license_class=oss&limit=20"
    releases = _fetch_json(url)
    for release in releases:
        ver = release.get("version", "")
        if release.get("is_prerelease"):
            continue
        if ver:
            return ver
    sys.exit(f"No stable release found for packer-plugin-{plugin_name}")


def fetch_galaxy_sha256(name: str, version: str) -> str:
    """Fetch the SHA-256 for an Ansible Galaxy collection tarball."""
    namespace, collection = name.split(".", 1)
    url = f"{GALAXY_API}/{namespace}/{collection}/versions/{version}/"
    data = _fetch_json(url)
    sha = data.get("artifact", {}).get("sha256", "")
    if not sha:
        sys.exit(f"No sha256 in Galaxy API response for {name} {version}")
    return sha


def verify_galaxy_version_exists(name: str, version: str) -> bool:
    """Check whether a specific collection version exists on Galaxy."""
    namespace, collection = name.split(".", 1)
    url = f"{GALAXY_API}/{namespace}/{collection}/versions/{version}/"
    try:
        _fetch_json(url)
        return True
    except Exception:
        return False


def load_versions(path: Path) -> dict:
    """Load .pinned_versions.yml."""
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not data:
        sys.exit(f"{path.name} is empty or invalid.")
    return data


def save_versions(path: Path, data: dict) -> None:
    """Write .pinned_versions.yml preserving the header comment."""
    with open(path) as fh:
        original = fh.read()

    header_lines: list[str] = []
    for line in original.splitlines():
        if line.startswith("---") or line.startswith("#"):
            header_lines.append(line)
        else:
            break

    header = "\n".join(header_lines) + "\n\n" if header_lines else ""
    body = yaml.dump(data, default_flow_style=False, sort_keys=False, width=120)
    path.write_text(header + body)


def refresh(data: dict, dry_run: bool = False) -> list[str]:
    """Refresh checksums in data dict. Returns list of changes made."""
    changes: list[str] = []

    ## Packer binary
    packer = data.get("packer", {})
    if packer.get("version") and packer.get("platform"):
        new_sha = fetch_packer_sha256(packer["version"], packer["platform"])
        old_sha = packer.get("sha256", "")
        if new_sha != old_sha:
            changes.append(
                f"packer {packer['version']}: "
                f"{old_sha[:16] or '(empty)'}... -> {new_sha[:16]}..."
            )
            if not dry_run:
                packer["sha256"] = new_sha

    ## pip packages
    for pkg in data.get("pip_packages", []):
        if pkg.get("name") and pkg.get("version"):
            new_sha = fetch_pip_sha256(pkg["name"], pkg["version"])
            old_sha = pkg.get("sha256", "")
            if new_sha != old_sha:
                changes.append(
                    f"pip {pkg['name']}=={pkg['version']}: "
                    f"{old_sha[:16] or '(empty)'}... -> {new_sha[:16]}..."
                )
                if not dry_run:
                    pkg["sha256"] = new_sha

    ## Packer plugins
    for plugin in data.get("packer_plugins", []):
        if plugin.get("name"):
            latest = fetch_packer_plugin_latest(plugin["name"])
            old_ver = plugin.get("version", "")
            if not old_ver:
                changes.append(
                    f"packer-plugin-{plugin['name']}: (empty) -> {latest}"
                )
                if not dry_run:
                    plugin["version"] = latest
            elif old_ver != latest:
                changes.append(
                    f"packer-plugin-{plugin['name']}: "
                    f"pinned at {old_ver} (latest is {latest}; "
                    f"update the version field to upgrade)"
                )

    ## Ansible collections
    for col in data.get("ansible_collections", []):
        if col.get("name") and col.get("version"):
            new_sha = fetch_galaxy_sha256(col["name"], col["version"])
            old_sha = col.get("sha256", "")
            if new_sha != old_sha:
                changes.append(
                    f"collection {col['name']} {col['version']}: "
                    f"{old_sha[:16] or '(empty)'}... -> {new_sha[:16]}..."
                )
                if not dry_run:
                    col["sha256"] = new_sha

    return changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh SHA-256 checksums for pinned dependencies."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any checksum would change (for CI).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing.",
    )
    args = parser.parse_args()

    if not VERSIONS_FILE.exists():
        sys.exit(f"{VERSIONS_FILE.name} not found. Create it first.")

    data = load_versions(VERSIONS_FILE)

    if args.check:
        changes = refresh(data, dry_run=True)
        if changes:
            print("Checksums are stale:")
            for c in changes:
                print(f"  {c}")
            sys.exit(1)
        else:
            print("All checksums are up to date.")
            sys.exit(0)

    if args.dry_run:
        changes = refresh(data, dry_run=True)
        if changes:
            print("Would update:")
            for c in changes:
                print(f"  {c}")
        else:
            print("Nothing to update.")
        return

    changes = refresh(data, dry_run=False)
    if changes:
        save_versions(VERSIONS_FILE, data)
        print(f"Updated {VERSIONS_FILE.name}:")
        for c in changes:
            print(f"  {c}")
        print()
        print("Remember to update the corresponding Ansible inventory files")
        print("if you changed any version numbers:")
        print("  - inventory/group_vars/builders_packer.yml (Packer, pip, plugins)")
        print("  - inventory/group_vars/windows_targets.yml (PowerSTIG, NuGet)")
        print("  - requirements.yml (Ansible collections)")
    else:
        print("All checksums are already up to date.")


if __name__ == "__main__":
    main()
