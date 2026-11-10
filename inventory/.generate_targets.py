#!/usr/bin/env python3
"""Generate targets.yml from .matrix.yml.

Reads the compact build matrix definition and produces the full Ansible
inventory file with every phantom host placed in all dimension groups.

Usage:
    python inventory/.generate_targets.py             # write targets.yml
    python inventory/.generate_targets.py --check     # exit 1 if stale
    python inventory/.generate_targets.py --dry-run   # print to stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML is required. Install it with: pip install pyyaml\n"
        "(It is already installed if Ansible is installed.)"
    )

SCRIPT_DIR = Path(__file__).resolve().parent
MATRIX_FILE = SCRIPT_DIR / ".matrix.yml"
TARGETS_FILE = SCRIPT_DIR / "targets.yml"

GENERATED_HEADER = """\
---
# THIS FILE IS GENERATED - DO NOT EDIT
#
# Source:    inventory/.matrix.yml
# Generator: inventory/.generate_targets.py
#
# Why is a generated file committed?  Ansible reads inventory from disk
# at invocation time; there is no build step where this could be created
# on the fly.  Committing it also means that matrix changes produce a
# reviewable diff in PRs.  The generator's --check flag (run in CI)
# ensures this file never drifts from the matrix definition.
#
# To change the build matrix, edit .matrix.yml and regenerate:
#   python inventory/.generate_targets.py
"""


def load_matrix(path: Path) -> dict:
    """Load and validate .matrix.yml.

    Ensures every os_version entry can resolve both a profile list
    and a build method, either from the entry itself, its family, or
    the global defaults.
    """
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not data or "os_versions" not in data:
        sys.exit(".matrix.yml must define 'os_versions'.")
    families = data.get("families", {})
    defaults = data.get("defaults", {})
    for os_key, os_cfg in data["os_versions"].items():
        family = os_cfg.get("family", "")
        family_cfg = families.get(family, {})

        # Profiles can come from three places: entry, family, or defaults.
        has_profiles = (
            "profiles" in os_cfg
            or "profiles" in family_cfg
            or "profiles" in defaults
        )
        if not has_profiles:
            sys.exit(
                f"No profiles for '{os_key}': set profiles on the entry, "
                f"its family '{family}', or in defaults."
            )

        # Method can come from the entry or the family (no global default;
        # build method is too important to silently inherit from a catch-all).
        has_method = "method" in os_cfg or "method" in family_cfg
        if not has_method:
            sys.exit(
                f"No method for '{os_key}': set method on the entry or "
                f"its family '{family}'."
            )
    return data


def generate_hosts(matrix: dict) -> list[dict]:
    """Compute the per-entry cross-product of profiles x clouds.

    For each os_version entry, resolves profiles, method, and clouds
    using the three-tier fallback (entry -> family -> defaults), then
    produces one host descriptor per profile x cloud combination.
    """
    defaults = matrix.get("defaults", {})
    families = matrix.get("families", {})
    default_profiles = defaults.get("profiles", [])
    # [None] sentinel: when no clouds are configured, hosts get no cloud
    # suffix and no cloud dimension group.
    default_clouds = defaults.get("clouds") or [None]

    hosts = []
    for os_key, os_cfg in matrix["os_versions"].items():
        family = os_cfg["family"]
        family_cfg = families.get(family, {})

        # Three-tier resolution: entry -> family -> defaults
        profiles = os_cfg.get("profiles", family_cfg.get("profiles", default_profiles))
        method = os_cfg.get("method", family_cfg["method"])
        clouds = os_cfg.get("clouds", default_clouds)

        for profile in profiles:
            for cloud in clouds:
                # Host name encodes all non-method dimensions:
                # <os_version>-<profile>-<cloud>  (e.g. rhel-9.8-database-aws)
                if cloud:
                    hostname = f"{os_key}-{profile}-{cloud}"
                else:
                    hostname = f"{os_key}-{profile}"
                hosts.append(
                    {
                        "hostname": hostname,
                        "family": family,
                        "version_group": os_cfg["version_group"],
                        "method": method,
                        "profile": "profile_" + profile.replace("-", "_"),
                        "cloud": f"cloud_{cloud}" if cloud else None,
                    }
                )
    return hosts


def _yaml_host_block(hostnames: list[str], indent: int) -> str:
    """Render a YAML 'hosts:' block with sorted hostnames.

    Each host gets the empty dict `{}` (no host-level vars; all vars
    come from group_vars).
    """
    pad = " " * indent
    lines = [f"{pad}hosts:"]
    for name in sorted(hostnames):
        lines.append(f"{pad}  {name}: {{}}")
    return "\n".join(lines)


def _collect(hosts: list[dict], key: str) -> dict[str, list[str]]:
    """Group hostnames by a descriptor key (e.g. "family" -> group members).

    Skips None values so the cloud dimension is omitted cleanly when
    no clouds are configured.
    """
    groups: dict[str, list[str]] = {}
    for h in hosts:
        val = h[key]
        if val is None:
            continue
        groups.setdefault(val, []).append(h["hostname"])
    return groups


def render_inventory(hosts: list[dict]) -> str:
    """Build the full YAML inventory string from host descriptors.

    Produces one group per unique value in each dimension, with every
    host listed under every group it belongs to. The output mirrors the
    structure of a hand-written targets.yml: builders (static), then
    vm_targets with children organized by dimension.

    We assemble the YAML as plain strings instead of using
    ``yaml.dump()`` because the output relies on section comments,
    controlled blank-line spacing, and a specific group ordering that
    PyYAML's emitter does not preserve or support without extensive
    subclassing. Since the entire file is generated from scratch (not
    edited in place), string assembly is simpler and keeps the output
    deterministic and diff-friendly.
    """
    # Pivot hosts into per-dimension group memberships.
    families = _collect(hosts, "family")
    versions = _collect(hosts, "version_group")
    profiles = _collect(hosts, "profile")
    methods = _collect(hosts, "method")
    clouds = _collect(hosts, "cloud")

    lines: list[str] = [GENERATED_HEADER]

    lines.append("all:")
    lines.append("  children:")

    # Builder groups are static shells; aws_ec2.yml populates them at runtime.
    lines.append("")
    lines.append("    # Builder groups (populated at runtime by aws_ec2.yml)")
    lines.append("    builders:")
    lines.append("      children:")
    lines.append("        builders_osbuild: {}")
    lines.append("        builders_packer: {}")

    lines.append("")
    lines.append("    # Build targets (phantom hosts)")
    lines.append("    vm_targets:")
    lines.append("      children:")

    # Dimension 1: OS family
    lines.append("")
    lines.append("        # DIMENSION 1: OS family")
    for group_name in sorted(families):
        lines.append(f"        {group_name}:")
        lines.append(_yaml_host_block(families[group_name], indent=10))

    # Dimension 2: OS version
    lines.append("")
    lines.append("        # DIMENSION 2: OS version")
    for group_name in sorted(versions):
        lines.append(f"        {group_name}:")
        lines.append(_yaml_host_block(versions[group_name], indent=10))

    # Dimension 3: Profile (nested under all_profiles parent group)
    lines.append("")
    lines.append("        # DIMENSION 3: Profile")
    lines.append("        all_profiles:")
    lines.append("          children:")
    for group_name in sorted(profiles):
        lines.append(f"            {group_name}:")
        lines.append(_yaml_host_block(profiles[group_name], indent=14))

    # Dimension 4: Build method
    lines.append("")
    lines.append("        # DIMENSION 4: Build method")
    for group_name in sorted(methods):
        lines.append(f"        {group_name}:")
        lines.append(_yaml_host_block(methods[group_name], indent=10))

    # Dimension 5: Cloud provider (omitted entirely when no clouds are configured)
    if clouds:
        lines.append("")
        lines.append("        # DIMENSION 5: Cloud provider")
        for group_name in sorted(clouds):
            lines.append(f"        {group_name}:")
            lines.append(_yaml_host_block(clouds[group_name], indent=10))

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate targets.yml from .matrix.yml."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if targets.yml is stale (for CI).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated YAML to stdout instead of writing.",
    )
    args = parser.parse_args()

    matrix = load_matrix(MATRIX_FILE)
    hosts = generate_hosts(matrix)
    output = render_inventory(hosts)

    if args.dry_run:
        print(output)
        return

    if args.check:
        if not TARGETS_FILE.exists():
            print(
                "targets.yml does not exist. Run:\n"
                "  python inventory/.generate_targets.py"
            )
            sys.exit(1)
        current = TARGETS_FILE.read_text()
        if current == output:
            print(f"targets.yml is up to date ({len(hosts)} hosts).")
            sys.exit(0)
        else:
            print(
                "targets.yml is stale. Run:\n"
                "  python inventory/.generate_targets.py"
            )
            sys.exit(1)

    TARGETS_FILE.write_text(output)

    # Summary stats for the console.
    host_count = len(hosts)
    dim_count = 4 + (1 if any(h["cloud"] for h in hosts) else 0)
    families = len(set(h["family"] for h in hosts))
    versions = len(set(h["version_group"] for h in hosts))
    profile_count = len(set(h["profile"] for h in hosts))
    method_count = len(set(h["method"] for h in hosts))
    clouds_count = len(set(h["cloud"] for h in hosts if h["cloud"]))

    print(f"Generated {TARGETS_FILE.name}:")
    print(f"  {host_count} phantom hosts across {dim_count} dimensions")
    print(
        f"  {families} families, {versions} versions, "
        f"{profile_count} profiles, {method_count} methods",
        end="",
    )
    if clouds_count:
        print(f", {clouds_count} clouds")
    else:
        print()


if __name__ == "__main__":
    main()
