# Inventory

> Back to [image-builder README](../README.md)

This directory holds the Ansible inventory for the image build pipeline: phantom host definitions, dynamic builder
discovery, and per-group variable files.

## Inventory Model

Build targets are modeled as **phantom hosts** in Ansible inventory. Each target (e.g., `rhel-9.4-base`) is an inventory
entry that doesn't represent a real SSH-able machine (it's a data carrier). Tasks run against these hosts use
`delegate_to` to execute on the actual builder.

Phantom hosts belong to four group dimensions:

1. **OS family** (`rhel8_targets`, `rhel9_targets`, `windows_targets`)
2. **OS version** (`rhel_9_4`, `rhel_8_10`, `windows_2022`)
3. **Profile** (`profile_base`, `profile_poc`)
4. **Build method** (`method_osbuild`, `method_packer`)

### Where Do Variables Go?

Each dimension is an independent axis of the build matrix. A phantom host sits at the intersection of all four and
merges their `group_vars`. The rule for placing a variable is: **put it in the dimension that determines its value**.

**Litmus tests by dimension:**

| Dimension       | group_vars example                         | Put a variable here if...                             |
|-----------------|--------------------------------------------|-------------------------------------------------------|
| 1. OS family    | `rhel9_targets.yml`, `windows_targets.yml` | Its value is determined by the OS platform and would  |
|                 |                                            | stay the same across all releases within the family.  |
| 2. OS version   | `rhel_9_4.yml`, `windows_2022.yml`         | Its value changes when you move from one release to   |
|                 |                                            | another within the same family (e.g. 9.4 -> 9.6, or   |
|                 |                                            | 2022 -> 2025).                                        |
| 3. Profile      | `all_profiles/`, `profile_poc.yml`         | It defines what the profile means for a build,        |
|                 |                                            | regardless of OS or build tool. Common config goes in |
|                 |                                            | `all_profiles/`; per-profile additions go in          |
|                 |                                            | `profile_*.yml`.                                      |
| 4. Build method | `method_osbuild.yml`, `method_packer.yml`  | It is about the build tool itself and would apply     |
|                 |                                            | regardless of which OS you build with that tool.      |

**Why RHEL and Windows split differently across dimensions 1 and 2:** RHEL has minor releases (9.4, 9.6, 9.8) that are
distinct base images you deliberately choose -- different package sets, different patch baselines. So "family" (dim 1) =
major version (rhel8 vs rhel9, each with its own blueprint template, STIG datastream, and package ecosystem), and
"version" (dim 2) = minor release. Windows Server has no minor releases -- just LTSC versions (2022, 2025) plus monthly
cumulative patches. There is no "Server 2022.4" to choose between. So "family" (dim 1) = all of Windows (shared Packer
template, connection settings), and "version" (dim 2) = the LTSC release year. This means settings that would be
family-level for RHEL (like STIG profiles) land in dim 2 for Windows, because the LTSC release is the version axis.

**Cross-dimension variables (the tricky case):** Some variables sit at the intersection of two dimensions -- they exist
*because of* one dimension but their *value* is determined by another. Place them in the dimension that determines the
value.

Concrete example: `packer_communicator` is a Packer setting (dimension 4), but its value (`winrm` for Windows, `ssh`
for Linux) is determined by the OS family (dimension 1). If you hypothetically added a "RHEL via Packer" target, you'd
need `packer_communicator: ssh` in the RHEL family group. So the variable lives in `windows_targets.yml` (dimension 1),
not `method_packer.yml` (dimension 4). The same logic applies to `packer_winrm_username` and `packer_instance_type`.

By contrast, `packer_binary` and `packer_template_dir` are tool-level settings whose values don't depend on the OS.
They live in `method_packer.yml` (dimension 4).

**Profile variables and OS-family prefixes:** Profile configuration uses composition: common/base config shared by
every profile lives in `group_vars/all_profiles/` (`_base_*` vars, split by OS family), while per-profile additions
live in each `group_vars/profile_*.yml` file (`_profile_specific_*` vars). The final `profile_*` variables consumed by
roles are Jinja expressions in the per-OS-family files that concatenate both layers automatically. Variable names
encode which OS family consumes them (e.g., `*_linux_packages`, `*_windows_extra_features`). See
`all_profiles/README.md` for composition rules and when to split further.

Builders use a stop/start managed lifecycle: they are stopped between pipeline runs to eliminate idle compute cost, and
started automatically at the beginning of each run. EBS volumes are preserved across stop/start cycles, so all installed
tooling and caches persist. Builders are discovered by the `amazon.aws.aws_ec2` dynamic inventory plugin via EC2 tags.
See ADR-IF-020 for the lifecycle decision. Future: Azure and GCP builder discovery plugins will be added.

## Quick Reference

### Adding a New Minor OS Version (e.g., RHEL 9.10)

A new minor version within an existing OS family. No playbook or role changes.

1. Add phantom hosts (`rhel-9.10-base`, `rhel-9.10-poc`) to `inventory/targets.yml`:
   - `rhel9_targets` (OS family group)
   - A new `rhel_9_10` version group
   - Each `profile_*` group the hosts belong to
   - `method_osbuild`
2. Create `inventory/group_vars/rhel_9_10.yml` with `os_version`
3. Done; new targets inherit RHEL 9 family settings, profile settings, and Image Builder method settings
   automatically.

### Adding a New Major OS Version (e.g., RHEL 10)

A new major version of an existing OS family. Requires a new family group and blueprint template, but no playbook
changes.

1. Add phantom hosts (e.g., `rhel-10.0-base`, `rhel-10.0-poc`) to `inventory/targets.yml`:
   - New OS family group: `rhel10_targets`
   - New version group: `rhel_10_0`
   - Existing `profile_*` and `method_osbuild` groups
2. Create `inventory/group_vars/rhel10_targets.yml` with `os_family`, `os_major`, `stig_profile`, `stig_datastream`,
   `stig_unselected_rules`, and `blueprint_template` (use the shared `rhel-blueprint.toml.j2`); modeled after
   `rhel9_targets.yml`
3. Create `inventory/group_vars/rhel_10_0.yml` with `os_version`
4. No playbook or template changes; `build_rhel.yml` targets `method_osbuild`, which already includes the new hosts,
   and `rhel-blueprint.toml.j2` uses inventory variables for all OS-version-specific values.

### Adding a New Profile

To add a new profile (e.g., `profile_hana`) across all OS versions:

1. Add `*-hana` hosts to each OS family group, version group, and `method_*` group in `inventory/targets.yml`
2. Add a new `profile_hana` child group under `all_profiles` in `inventory/targets.yml` containing all new hosts
3. Create `inventory/group_vars/profile_hana.yml` with `profile: hana` and any `_profile_specific_*` vars for the
   profile's additions (modeled after `profile_poc.yml`). Common/base config is inherited from `all_profiles/`
   automatically.
4. No playbook or role changes needed.

### Adding a New OS Family (e.g., Ubuntu)

A completely new OS family requires new roles and a new playbook entry in `site.yml`.

1. **Inventory** (`inventory/targets.yml`):
   - New OS family group (e.g., `ubuntu24_targets`)
   - New version group(s) (e.g., `ubuntu_24_04`)
   - Add hosts to existing `profile_*` groups
   - New build method group if the install method differs (e.g., `method_autoinstall` for Ubuntu's cloud-init
     autoinstall)
2. **Group vars** (`inventory/group_vars/`):
   - Family vars (e.g., `ubuntu24_targets.yml`): `os_family`, `os_major`, STIG/CIS profile, install template reference
   - Version vars (e.g., `ubuntu_24_04.yml`): `os_version`
   - Build method vars if new (e.g., `method_autoinstall.yml`): `builder_group`
3. **Roles** (`roles/`):
   - New build role (e.g., `ubuntu_image_build/`) with install template
   - New hardening role (e.g., `ubuntu_hardening/`) for OS-specific STIG/CIS tooling
   - Existing roles reused as-is: `builder_configure`, `cloud_init_prep`, `image_export`, `cloud_convert`, `image_distribute`
4. **Playbooks**:
   - New build playbook (e.g., `playbooks/build_ubuntu.yml`) targeting the new build method group
   - Add an `import_playbook` entry in `playbooks/site.yml`

**Key difference from adding a RHEL version:** a new OS family needs new roles and a `site.yml` entry; a new RHEL
version does not.
