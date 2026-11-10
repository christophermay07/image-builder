# Inventory

> Back to [image-builder README](../README.md)

This directory holds the Ansible inventory for the image build pipeline: phantom host definitions, dynamic builder
discovery, and per-group variable files.

## Directory Layout

```
inventory/
  .matrix.yml             # Build matrix definition (the ONLY file to edit for matrix changes)
  .generate_targets.py    # Generates targets.yml from .matrix.yml
  targets.yml             # GENERATED - do not edit by hand
  aws_ec2.yml             # Dynamic inventory plugin for builder discovery
  group_vars/
    all.yml               # Global defaults (Artifactory, builder infra, shared paths)
    builders.yml          # Shared builder settings (SSH, Python)
    builders_osbuild.yml  # osbuild builder packages and config
    builders_packer.yml   # Packer builder packages and config
    method_osbuild.yml    # Dimension 4: osbuild build method settings
    method_packer.yml     # Dimension 4: Packer build method settings
    rhel_targets.yml      # Dimension 1: RHEL OS family (all major versions)
    windows_targets.yml   # Dimension 1: Windows OS family
    ubuntu_targets.yml    # Dimension 1: Ubuntu OS family
    rhel_8_10.yml         # Dimension 2: RHEL 8.10 version
    rhel_9_2.yml          # Dimension 2: RHEL 9.2 version
    rhel_9_4.yml          # ...
    rhel_9_6.yml
    rhel_9_8.yml
    windows_2022.yml      # Dimension 2: Windows Server 2022 version
    windows_2025.yml      # Dimension 2: Windows Server 2025 version
    ubuntu_22_04.yml      # Dimension 2: Ubuntu 22.04 LTS version
    ubuntu_24_04.yml      # Dimension 2: Ubuntu 24.04 LTS version
    ubuntu_26_04.yml      # Dimension 2: Ubuntu 26.04 LTS version
    profile_base.yml      # Dimension 3: base profile (all families)
    profile_appserver.yml # Dimension 3: application server (RHEL)
    profile_database.yml  # Dimension 3: database (RHEL)
    profile_jumphost.yml  # Dimension 3: bastion/jumphost (Windows)
    profile_k8s_node.yml  # Dimension 3: K8s node (Ubuntu)
    cloud_aws.yml         # Dimension 5: AWS cloud settings + image creds
    cloud_azure.yml       # Dimension 5: Azure cloud settings
    cloud_gcp.yml         # Dimension 5: GCP cloud settings
    all_profiles/         # Dimension 3: common profile composition layer
      linux.yml
      windows.yml
      README.md
```

## Inventory Model

There are two kinds of hosts in this inventory:

### Builder Hosts (Real Machines)

The `builders` group in `targets.yml` contains two child groups: `builders_osbuild` and `builders_packer`.
These groups **start empty** in `targets.yml`. They are populated at runtime by the `aws_ec2.yml` dynamic
inventory plugin, which discovers running EC2 instances and sorts them into groups based on their `builder_type`
tag:

- `builder_type=osbuild` -> `builders_osbuild` group
- `builder_type=packer` -> `builders_packer` group

The child groups exist so each builder type gets different tooling installed by `roles/builder_configure/`.
osbuild builders get `osbuild-composer`; Packer builders get the Packer binary and WinRM plugins.

**Static builders** (current state): persistent EC2 instances that are started/stopped each pipeline run.
`start_builders.yml` starts them; `stop_builders.yml` stops them. EBS volumes are preserved across stop/start
cycles, so all installed tooling and caches persist. Builders are discovered by the `amazon.aws.aws_ec2`
dynamic inventory plugin via EC2 tags (`purpose: image-builder`). See ADR-IB-020 for the lifecycle
decision.

**Ephemeral builders** (also supported): `provision_builders.yml` launches fresh EC2 instances from pre-baked
AMIs and tags them identically. The `aws_ec2.yml` dynamic inventory discovers them the same way; nothing in
`targets.yml` changes when switching from static to ephemeral builders. The builder groups still start empty,
still get filled by `aws_ec2.yml`, and the rest of the pipeline is unaware of whether builders are persistent
or ephemeral. The only difference is an extra tag (`ephemeral=true`) that `teardown_builders.yml` uses to
terminate only ephemeral instances, without touching static builders if any coexist.

### Phantom Hosts (Build Targets)

Everything under `vm_targets` is a **phantom host**. These are NOT real machines. Each one (e.g.,
`rhel-9.4-base-aws`) represents a single image to build. It carries variables from the groups it belongs to.
Playbooks target these "hosts," then use `delegate_to` to run the actual work on a real builder.

Each host is listed as `hostname: {}` in `targets.yml`. The `{}` means "no host-level variables." All
variables come from `group_vars/` files, resolved by which groups the host belongs to. A host in multiple
groups inherits variables from ALL of them; Ansible merges by precedence (see
[Ansible variable precedence](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html#variable-precedence-where-should-i-put-a-variable)).

Each phantom host belongs to exactly **five groups**, one per dimension:

**Concrete example:** `rhel-9.4-base-aws` is simultaneously in:

| Dimension         | Group             | group_vars file          |
|-------------------|-------------------|--------------------------|
| 1. OS family      | `rhel_targets`    | `rhel_targets.yml`       |
| 2. OS version     | `rhel_9_4`        | `rhel_9_4.yml`           |
| 3. Profile        | `profile_base`    | `profile_base.yml`       |
| 4. Build method   | `method_osbuild`  | `method_osbuild.yml`     |
| 5. Cloud provider | `cloud_aws`       | `cloud_aws.yml`          |

When a playbook runs against this host, Ansible merges variables from all five `group_vars` files (plus
`all.yml` and `all_profiles/`). This is the core mechanism that lets the pipeline compose the right
configuration for any combination of OS, profile, method, and cloud without per-host variable overrides.

**Do not remove any of the five dimensions.** Every dimension serves a distinct purpose, and roles depend on
variables from each one. Removing a dimension's groups would leave variables unresolvable.

Host names encode all non-method dimensions: `<os_version>-<profile>-<cloud>` (e.g., `rhel-9.4-base-aws`,
`windows-2022-jumphost-gcp`, `ubuntu-26.04-k8s-node-azure`). The build method is not in the hostname because
it is determined entirely by the OS family and does not vary within a family.

### Generated Inventory

The `targets.yml` file is generated from `.matrix.yml` by `.generate_targets.py`. **Do not edit `targets.yml` by
hand.** To change the build matrix, edit `.matrix.yml` and regenerate:

```bash
python inventory/.generate_targets.py           # write targets.yml
python inventory/.generate_targets.py --check   # exit 1 if stale (for CI)
python inventory/.generate_targets.py --dry-run # preview without writing
```

The `.matrix.yml` file has three sections:

- **`defaults`**: cloud list shared by most OS versions.
- **`families`**: build method and profile list per OS family. Every OS version inherits its family's profiles
  and method.
- **`os_versions`**: the actual build targets. Each entry specifies a `family` and `version_group`, inheriting
  profiles, method, and clouds from its family and defaults. An entry can optionally override any of these.

The generator uses **three-tier resolution** for each OS version entry:

1. Check the entry itself for `profiles`, `method`, or `clouds`
2. Fall back to the family for `profiles` and `method`
3. Fall back to `defaults` for `clouds`

This means most entries are just two lines (`family` + `version_group`), with overrides only where needed.

```yaml
# .matrix.yml structure
defaults:
  clouds: [aws, azure, gcp]

families:
  rhel_targets:
    method: method_osbuild               # all RHEL uses osbuild
    profiles: [base, appserver, database]        # RHEL gets these three profiles
  windows_targets:
    method: method_packer                 # all Windows uses Packer
    profiles: [base, jumphost]
  ubuntu_targets:
    method: method_packer                 # all Ubuntu uses Packer
    profiles: [base, k8s-node]

os_versions:
  rhel-9.8:
    family: rhel_targets                  # inherits method + profiles from family
    version_group: rhel_9_8              # inherits clouds from defaults
  windows-2022:
    family: windows_targets
    version_group: windows_2022
  # Override example: restrict one version to AWS only
  # rhel-9.8:
  #   family: rhel_targets
  #   version_group: rhel_9_8
  #   clouds: [aws]                       # overrides defaults.clouds
```

Not every OS family gets the same profiles. RHEL gets `base`, `appserver`, `database`; Windows gets `base`,
`jumphost`; Ubuntu gets `base`, `k8s-node`. All OS versions currently target all three clouds. An individual
OS version can override either list if it needs to diverge from its family or the cloud defaults.

## Where Do Variables Go?

Each dimension is an independent axis of the build matrix. A phantom host sits at the intersection of all five
and merges their `group_vars`. The rule for placing a variable is: **put it in the dimension that determines its
value**.

For how inventory sources relate to role fallbacks, required inputs, credentials, and upstream facts, see
[Role input validation](../README.md#role-input-validation).

### Litmus Tests by Dimension

| Dimension         | group_vars example                        | Put a variable here if...                         |
|-------------------|-------------------------------------------|---------------------------------------------------|
| 1. OS family      | `rhel_targets.yml`, `ubuntu_targets.yml`  | Its value is determined by the OS platform and    |
|                   |                                           | stays the same across all releases within the     |
|                   |                                           | family.                                           |
| 2. OS version     | `rhel_9_4.yml`, `ubuntu_24_04.yml`        | Its value changes when you move from one release  |
|                   |                                           | to another within the same family (e.g. 9.4 ->    |
|                   |                                           | 9.6, 2022 -> 2025, or 22.04 -> 24.04).            |
| 3. Profile        | `all_profiles/`, `profile_database.yml`   | It defines what the profile means for a build,    |
|                   |                                           | regardless of OS, build tool, or cloud. Common    |
|                   |                                           | config goes in `all_profiles/`; per-profile       |
|                   |                                           | additions go in `profile_*.yml`.                  |
| 4. Build method   | `method_osbuild.yml`, `method_packer.yml` | It is about the build tool itself and would apply |
|                   |                                           | regardless of which OS or cloud you build for.    |
| 5. Cloud provider | `cloud_aws.yml`, `cloud_gcp.yml`          | It is specific to the target cloud. NTP servers,  |
|                   |                                           | vendor agent config, cloud API credentials, and   |
|                   |                                           | image distribution settings all live here.        |

### How Dimensions 1 and 2 Work Together

All three OS families follow the same 2-tier pattern:

- **Dimension 1 (family)**: one group per OS platform; `rhel_targets`, `windows_targets`, `ubuntu_targets`.
- **Dimension 2 (version)**: one group per distinct base image; `rhel_9_4`, `windows_2022`, `ubuntu_24_04`.

Family group_vars carry settings that are truly shared across every version: `os_family`, build tooling
config, and (for RHEL) `stig_profile`, `blueprint_template`, `yum_repo_base_url`, and `yum_repo_gpgkey`.
Version group_vars carry anything that changes between releases.

**RHEL version files carry one value that is duplicated across minor versions within a major release**:
`stig_unselected_rules` (currently empty for all versions). Other per-major-version values (`os_major`,
`stig_datastream`) are derived automatically in `rhel_targets.yml` from `os_version`, so adding a new minor
version only requires setting `os_version` and `stig_unselected_rules`.

### Cross-Dimension Variables (The Tricky Case)

Some variables sit at the intersection of two dimensions; they exist *because of* one dimension but their
*value* is determined by another. Place them in the dimension that determines the value.

Concrete example: `packer_communicator` is a Packer setting (dimension 4), but its value (`winrm` for Windows,
`ssh` for Linux) is determined by the OS family (dimension 1). If you hypothetically added a "RHEL via Packer"
target, you'd need `packer_communicator: ssh` in the RHEL family group. So the variable lives in
`windows_targets.yml` (dimension 1), not `method_packer.yml` (dimension 4). The same logic applies to
`packer_winrm_username` and `packer_instance_type`. Ubuntu also sets `packer_communicator: ssh` in
`ubuntu_targets.yml` for the same reason.

The Windows build role consumes `packer_communicator` in its Packer template and provides a `winrm` fallback in role
defaults. It currently accepts only `winrm`, because its connection settings and bootstrap require WinRM. Ubuntu's
`ssh` setting is retained for its forthcoming build role; it has no executable consumer yet. That role should provide
an `ssh` fallback and consume the value through an SSH-capable template.

By contrast, `packer_binary` and `packer_template_dir` are tool-level settings whose values don't depend on the
OS. They live in `method_packer.yml` (dimension 4).

### Cloud-Specific Overrides (Dimension 5)

AWS RHEL builds also require `rhel_smoke_subnet_id` and `rhel_smoke_security_group_ids`
in `cloud_aws.yml` or extra-vars.
The validation guest receives a private IP; its security groups must permit SSH from the assigned builder.
`builders_osbuild.yml` installs `openssh-clients` and `coreutils` for authenticated SSH validation.
All clouds use the same registration, validation, and publication sequence. Azure/GCP inventory files identify the
remaining provider configuration TODOs; their unfinished handlers block publication. See
[cloud_validate](../roles/cloud_validate/README.md) for the common image identity and smoke-result fields.

Each `cloud_*.yml` file sets `cloud_target` to a string (e.g., `cloud_target: aws`). The `cloud_convert` and
`image_distribute` roles dispatch to provider-specific task files based on cloud group membership (e.g.,
`when: "'cloud_aws' in group_names"`), so each phantom host naturally follows only the correct cloud path.

Per-cloud settings like NTP servers (`chrony_config`), cloud-init datasources, vendor agent configuration,
image conversion buckets, distribution targets, and cloud API credentials all belong in the cloud dimension.

Builder infrastructure settings (start/stop builder EC2 instances, builder tags, ephemeral builder config)
live in `all.yml` because builders run on AWS regardless of which cloud the images target. See the
`aws_builder_*` variables in `all.yml`.

### Profile Variables and OS-Family Prefixes

Profile configuration uses composition: common/base config shared by every profile lives in
`group_vars/all_profiles/` (`_base_*` vars, split by OS family), while per-profile additions live in each
`group_vars/profile_*.yml` file (`_profile_specific_*` vars). The final `profile_*` variables consumed by
roles are Jinja expressions in the per-OS-family files that concatenate both layers automatically. Variable
names encode which OS family consumes them (e.g., `*_linux_packages`, `*_windows_extra_features`). See
`all_profiles/README.md` for composition rules and when to split further.

### Yum Repository Variables (Cross-Dimension)

Yum repos are one of the few variables that span three dimensions. The final `build_yum_sources` list is
composed from three layers, each from a different dimension:

| Layer                                 | Dimension   | File                     | Purpose                             |
|---------------------------------------|-------------|--------------------------|-------------------------------------|
| `_base_build_yum_sources`             | 3 (profile) | `all_profiles/linux.yml` | Repos every RHEL image needs        |
| `_profile_specific_build_yum_sources` | 3 (profile) | `profile_*.yml`          | Repos for one profile (e.g.         |
|                                       |             |                          | application workloads)              |
| `_cloud_build_yum_sources`            | 5 (cloud)   | `cloud_*.yml`            | Repos for one cloud (e.g. Azure)    |

Shared settings (`yum_repo_base_url`, `yum_repo_gpgkey`) live in dimension 1 (`rhel_targets.yml`)
because they are RHEL-family-level values that every repo entry references via Jinja.

`blueprint_yum_repos` (repos in the final image's `/etc/yum.repos.d/`) currently aliases
`build_yum_sources` so both lists are identical. The composition expression and detailed entry format are
documented in `all_profiles/README.md`.

### Dimension 4: The Routing Dimension

Build method is not just a variable axis; it is the **critical routing dimension** that determines which type
of builder a target's work gets delegated to.

Each method's group_vars file sets `build_method`, and `all.yml` derives `builder_group` from it:

```
group_vars/method_osbuild.yml  ->  build_method: osbuild  ->  builder_group: builders_osbuild
group_vars/method_packer.yml   ->  build_method: packer   ->  builder_group: builders_packer
```

The `builder_group` variable connects phantom hosts to real builder machines. The build roles
(`rhel_image_build`, `windows_image_build`) assign `_builder_host` **once per phantom host** using round-robin
across the builder group. All downstream roles in the play inherit that fact, so every step for a given target
(build, export, convert, distribute, cleanup) delegates to the same builder. See
`rhel_image_build/tasks/main.yml` for the round-robin logic.

Playbooks target method groups directly:

- `build_rhel.yml` targets `hosts: method_osbuild`
- `build_windows.yml` targets `hosts: method_packer`

This means adding a new build method requires:

1. A `method_<name>.yml` group_vars file setting `build_method: <name>` (phantom-host side)
2. A `builders_<name>.yml` group_vars file setting `builder_type: <name>` and packages (real-host side)
3. EC2 instances tagged `builder_type=<name>` so `aws_ec2.yml` creates the `builders_<name>` group
4. A new build playbook targeting the new method group

The duplication between phantom hosts (`build_method`) and real hosts (`builder_type`) exists because they are
separate inventory populations. Phantom hosts know which method they use; EC2 instances know what they are.
Both derive the same group name independently (`builders_<name>`). If the two sides produce different group
names, the builder lookup will find an empty group and fail.

## Quick Reference

All matrix changes follow the same workflow: edit `.matrix.yml`, regenerate, create any new `group_vars` files.

### Adding a New Minor OS Version (e.g., RHEL 9.10)

A new minor version within an existing OS family. No playbook or role changes.

1. Add an entry to `.matrix.yml` under `os_versions`:
   ```yaml
   rhel-9.10:
     family: rhel_targets
     version_group: rhel_9_10
   ```
   That's it; `method` and `profiles` are inherited from the `rhel_targets` family, and `clouds` from
   `defaults`.
2. Run `python inventory/.generate_targets.py`
3. Create `inventory/group_vars/rhel_9_10.yml` with `os_version` and `stig_unselected_rules`;
   copy from an existing 9.x file (e.g. `rhel_9_8.yml`).
4. Done. The generator places hosts in all five dimension groups. New targets inherit RHEL family settings,
   profile settings, method settings, and cloud settings automatically.

### Adding a New Major OS Version (e.g., RHEL 10)

A new major version within the existing RHEL family. No new family entry is needed; the `rhel_targets` family
already covers all RHEL versions. No playbook changes required.

1. Add an OS version entry to `.matrix.yml`:
   ```yaml
   os_versions:
     rhel-10.0:
       family: rhel_targets
       version_group: rhel_10_0
   ```
2. Run `python inventory/.generate_targets.py`
3. Create `inventory/group_vars/rhel_10_0.yml` with `os_version: "10.0"` and `stig_unselected_rules: []`.
   `os_major` and `stig_datastream` are derived automatically by `rhel_targets.yml`.
4. No playbook or template changes needed; `build_rhel.yml` targets `method_osbuild`, which already includes
   the new hosts, and `rhel-blueprint.toml.j2` uses inventory variables for all OS-version-specific values.

### Adding a New Profile

Profiles are defined per OS family in `.matrix.yml`. Add the profile to the relevant family's `profiles`
list, or to a specific OS version entry if it should only apply there.

1. Add the profile name to the family's `profiles` list in `.matrix.yml`:
   ```yaml
   families:
     rhel_targets:
       method: method_osbuild
       profiles: [base, appserver, database, newprofile]    # <-- add here
   ```
   Or, if it applies to only one OS version, add it directly on that entry:
   ```yaml
   os_versions:
     rhel-9.8:
       family: rhel_targets
       version_group: rhel_9_8
       profiles: [base, appserver, database, newprofile]    # overrides family
   ```
2. Run `python inventory/.generate_targets.py`
3. Create `inventory/group_vars/profile_newprofile.yml` with `profile: newprofile` and any
   `_profile_specific_*` vars; modeled after `profile_appserver.yml`. Common/base config is inherited from
   `all_profiles/` automatically.
4. No playbook or role changes needed.

### Adding a New Cloud Provider

Like profiles, clouds can be added to `defaults.clouds` (applies to all OS versions) or to specific entries.

1. Add the cloud name to `defaults.clouds` in `.matrix.yml` (or to specific entries' `clouds` lists):
   ```yaml
   defaults:
     clouds:
       - aws
       - azure
       - gcp
       - oci    # <-- add here
   ```
2. Run `python inventory/.generate_targets.py`
3. Create `inventory/group_vars/cloud_oci.yml` with `cloud_target: oci`, cloud-init datasource ordering,
   chrony NTP config, and cloud-specific settings (image conversion buckets, distribution targets, API
   credentials). Use `cloud_aws.yml` as a model.
4. Implement native registration in `cloud_convert`, boot/SSH/cleanup in `cloud_validate`, provider approval in
   `image_release_approve`, and distribution in `image_distribute` for the new cloud.
   Follow the existing provider task files; unfinished handlers must stop rather than grant publication or approval.
5. Add provider dispatch entries in those roles; keep `build_rhel.yml` provider-neutral:
   ```yaml
   - name: Convert for OCI
     ansible.builtin.include_tasks: convert_oci.yml
     when: "'cloud_oci' in group_names"
   ```

All producers follow the [release approval contract](../roles/image_release_approve/README.md): initialize through
`image_build_initialize`, build/register and validate the native image, call `image_validation_gate`, prepare their
artifact list, and invoke upload, bundling, and approval explicitly.
Distribution uses only cloud dispatch and that record. Do not add OS- or build-method-specific distribution branches.

### Adding a New OS Family (e.g., a Hypothetical New Platform)

A completely new OS family requires new roles and a new playbook entry in `site.yml`. Ubuntu is already in the
matrix; this section documents the pattern for future families.

Ubuntu follows the Windows split pattern, not the RHEL pattern: "family" (dim 1) = all Ubuntu LTS versions
(`ubuntu_targets`), and "version" (dim 2) = the LTS release (`ubuntu_22_04`, `ubuntu_24_04`, etc.). Like
Windows LTSC versions, Ubuntu LTS releases have no meaningful sub-versions to choose between, and all LTS
releases share the same build tooling (apt, ssh, cloud-init/autoinstall).

1. **Matrix** (`.matrix.yml`): add a family entry with the build method and profiles, then add OS version
   entries referencing it.
2. **Regenerate:** `python inventory/.generate_targets.py`
3. **Group vars** (`inventory/group_vars/`):
   - Family vars (e.g., `ubuntu_targets.yml`): `os_family`, STIG/CIS profile, Packer connection settings
   - Version vars (e.g., `ubuntu_24_04.yml`): `os_version`, `source_ami`
   - Build method vars if new (e.g., `method_autoinstall.yml`): `build_method`
4. **Roles** (`roles/`):
   - New build role (e.g., `ubuntu_image_build/`) with install template
   - New hardening role (e.g., `ubuntu_hardening/`) for OS-specific STIG/CIS tooling
   - Reuse `image_build_initialize`, `image_validation_gate`, `artifactory_upload`, `artifactory_release_bundle`,
     `image_release_approve`, and `image_distribute`.
   - Add a separate artifact-preparation role to generate metadata and select files, or reuse one when its artifact
     and metadata contracts match. Sharing an OS or build method alone does not establish compatibility.
     Use `cloud_convert` only when the build tool does not already produce a native image.
5. **Playbooks**:
   - New build playbook (e.g., `playbooks/build_ubuntu.yml`) targeting the new build method group
   - Add an `import_playbook` entry in `playbooks/site.yml`

**Key difference from adding an OS version:** a new OS family needs new roles and a `site.yml` entry; a new
version within an existing family does not.

### Removing Anything

Delete the entry from `.matrix.yml` and regenerate. The generator removes all references across all dimension
groups automatically.

- **Remove a profile:** delete the name from its family's `profiles` list (and any per-entry overrides),
  regenerate, optionally delete the `profile_*.yml` group_vars file.
- **Remove a cloud:** delete the name from `defaults.clouds` and/or any per-entry `clouds` lists,
  regenerate, optionally delete the `cloud_*.yml` group_vars file.
- **Remove an OS version:** delete the entry from `os_versions`, regenerate, optionally delete the version
  group_vars file. If this was the last version in its family, also remove the family entry from `families`
  and the family group_vars file.
- **Restrict a profile to fewer OS versions:** move it from the family list into explicit per-entry
  `profiles` overrides on only the OS versions that need it, then regenerate.
- **Restrict a cloud to fewer OS versions:** move it from `defaults.clouds` into explicit per-entry `clouds`
  overrides, then regenerate.

### Filtering the Matrix

Ansible's `--limit` flag intersects across dimension groups:

```bash
# Single host
ansible-playbook playbooks/build_rhel.yml --limit rhel-9.4-base-aws

# All RHEL 9 base images on AWS (pattern matches version groups)
ansible-playbook playbooks/build_rhel.yml --limit 'rhel_9_*:&profile_base:&cloud_aws'

# Everything targeting GCP
ansible-playbook playbooks/site.yml --limit cloud_gcp

# All Ubuntu k8s-node images
ansible-playbook playbooks/build_ubuntu.yml --limit 'ubuntu_targets:&profile_k8s_node'

# All database images across all clouds
ansible-playbook playbooks/build_rhel.yml --limit profile_database

# RHEL 9.8 on Azure only
ansible-playbook playbooks/build_rhel.yml --limit 'rhel_9_8:&cloud_azure'
```

## CI: Staleness Check

Add this to CI to catch cases where someone edits `.matrix.yml` but forgets to regenerate:

```bash
python inventory/.generate_targets.py --check
```

Exits 0 if `targets.yml` matches what `.matrix.yml` would produce; exits 1 with a message if stale.

## Builder-side Ansible handoff

Windows builds use `builder_pip_packages` from the assigned builder and the pinned collections and roles from the
project `requirements.yml`. `builder_configure` installs Python 3.12, pip, and Git; `builder_ansible_prepare` installs
the runtime and content separately for every build. Public GitHub remains the source for `win2022stig` version `2.9.0`.

Put Windows provider rule toggles in `windows_stig_overrides`, for example `wn22_cc_000500: false` within that mapping.
The accepted format is `wnYY_XX_NNNNNN` with boolean values; both `wn22_*` and `wn25_*` names are accepted.
Bare provider variables on phantom hosts are not forwarded. Composed profile features and registry settings are
forwarded automatically. Future guest operating systems can reuse preparation with their own dependency/input lists.
