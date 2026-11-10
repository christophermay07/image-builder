# all_profiles: common profile configuration

Variables in this directory are inherited by **every** profile.
Per-profile overlays live in `group_vars/profile_*.yml`.

## Why base config lives here, not in `profile_base.yml`

From a business perspective, "base" is the foundation that everything inherits from: every profile gets the
common packages, services, and filesystem layout defined here. That sounds like it belongs in the base profile,
but it can't, because Ansible variable precedence is group-scoped.

`profile_base.yml` is group_vars for the `profile_base` **child** group. Only hosts in that group (the ones
that literally build a "base" image with no workload extras) see its variables. A host like `rhel-9.8-database-aws`
is in `profile_database`, not `profile_base`, so it would never inherit anything from `profile_base.yml`.

`all_profiles/` is group_vars for the `all_profiles` **parent** group, which contains every `profile_*` child.
Variables defined here are inherited by all profiles automatically. That is why the shared foundation lives
here: it is the only place Ansible's precedence rules make it visible to every host.

The `profile_base` group still needs to exist because we build base images (vanilla hardened, no workload
extras). Its group_vars file (`profile_base.yml`) just sets `profile: base` as metadata; the base profile's
behavior is entirely the defaults defined in this directory, with no `_profile_specific_*` overrides.

## How composition works

| Prefix                | Purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `_base_*`             | Base config shared by every profile (defined here).                     |
| `_profile_specific_*` | Per-profile additions (default `[]` here, overridden in profile files). |
| `profile_*`           | Final composed value (Jinja expression, consumed by roles/templates).   |

Ansible evaluates the Jinja expressions lazily using each host's resolved variable values, so child-group
overrides in `profile_database.yml` etc. are picked up automatically.

Some composed variables use domain-specific names instead of the `profile_*` prefix: `build_yum_sources`,
`blueprint_yum_repos`, and `blueprint_filesystem_layout`. They follow the same `_base` + `_profile_specific`
composition pattern; only the final variable name differs.

## Yum repository composition

Yum repos use a three-layer composition with an additional cloud-specific layer:

```
build_yum_sources = _base_build_yum_sources          (all_profiles/linux.yml)
                  + _profile_specific_build_yum_sources   (profile_*.yml)
                  + _cloud_build_yum_sources              (cloud_*.yml)
```

`blueprint_yum_repos` (the repos baked into the final image's `/etc/yum.repos.d/`) currently points at
`build_yum_sources` so both lists are identical. If they need to diverge, the comment above the variable in
`linux.yml` explains how to restore a separate composition.

### Where each layer lives

| Layer                                  | File                     | What goes here                                   |
|----------------------------------------|--------------------------|--------------------------------------------------|
| `_base_build_yum_sources`              | `all_profiles/linux.yml` | Repos every RHEL image needs (e.g., BaseOS,      |
|                                        |                          | AppStream)                                       |
| `_profile_specific_build_yum_sources`  | `profile_*.yml`          | Repos needed by a specific profile (e.g., High   |
|                                        |                          | Availability)                                    |
| `_cloud_build_yum_sources`             | `cloud_*.yml`            | Repos only one cloud needs (Azure-specific)      |
| `yum_repo_base_url`, `yum_repo_gpgkey` | `rhel_targets.yml`       | Shared setting referenced via Jinja in repo      |
|                                        |                          | entries                                          |

### Jinja interpolation in repo entries

Repo entries use Jinja variables that Ansible resolves per host. This means you define each repo **once**
and it automatically gets the right version for every build target:

```yaml
- id: "rhel-{{ os_major }}-for-x86_64-baseos-rpms"
  baseurl: "https://{{ yum_repo_base_url }}/redhat{{ os_major }}/{{ os_version }}/..."
  gpgkey: "{{ yum_repo_gpgkey }}"
```

Available variables in repo entries:

| Variable                  | Source             | Example            | What it resolves to                     |
|---------------------------|--------------------|--------------------|-----------------------------------------|
| `{{ os_major }}`          | `rhel_targets.yml` | `9`                | Major version (derived from os_version) |
| `{{ os_version }}`        | `rhel_*_*.yml`     | `9.6`              | Full version string                     |
| `{{ yum_repo_base_url }}` | `rhel_targets.yml` | `repo.example.com` | Mirror hostname/path                    |

### Restricting repos by RHEL major version

The optional `os_major` field on a repo entry restricts it to specific RHEL major versions. It accepts
a single value or a list:

```yaml
# Only RHEL 9
os_major: "9"

# RHEL 8 and 9, but not 10+
os_major: ["8", "9"]
```

Repos without `os_major` apply to all RHEL versions. The filter works by normalizing the value into a
list using `[x] | flatten` and checking membership. This happens in both the blueprint template
(for `[[customizations.repositories]]` blocks) and the build source task file (for `composer-cli sources add`).

### Adding a repo

1. Decide which layer it belongs to (base, profile-specific, or cloud-specific).
2. Add the entry to the appropriate file with the standard fields (`id`, `name`, `baseurl`, `gpgcheck`,
   `gpgkey`). Use Jinja variables for version and URL components.
3. Add `os_major` only if the repo does not exist on all RHEL major versions.
4. Run `yamllint` and `ansible-lint` to verify.

### Repo entry format reference

```yaml
- id: "repo-id"                                        # required; becomes [section-name] in .repo file
  name: "Human Readable Name (RPMs)"                   # optional; repo description
  baseurl: "https://{{ yum_repo_base_url }}/path/..."  # required; may use Jinja
  gpgcheck: 1                                          # optional; default true
  gpgkey: "{{ yum_repo_gpgkey }}"                      # optional; GPG key URL
  enabled: 1                                           # optional; default true (see note below)
  os_major: ["8", "9"]                                 # optional; restrict to specific major versions
```

The `enabled` field controls whether the repo is active in the **final image** only. Build-time sources
(`composer-cli sources add`) always have the repo enabled during the compose regardless of this field;
osbuild sources have no concept of "disabled." In the final image's `/etc/yum.repos.d/`, repos default
to `enabled=1`. Set `enabled: 0` for repos that should ship in the image but stay disabled until an
admin explicitly enables them (e.g. Microsoft Packages for RHEL).

## YAML syntax notes for editors

**Lists:** `[]` means "empty list." When adding items, DELETE the `[]` and use block sequence syntax (`- item`)
on the following lines. Example:

```yaml
# BEFORE:
_base_linux_packages: []

# AFTER:
_base_linux_packages:
  - tuned-profiles-throughput-performance
  - compat-c++-12
```

**Dicts:** `{}` means "empty dict." When adding entries, DELETE the `{}` and put the key/value mappings on the
following lines (indented). Example:

```yaml
# BEFORE:
_base_windows_registry_entries: {}

# AFTER:
_base_windows_registry_entries:
  app_memory_management:
    path: "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management"
    name: LargeSystemCache
    data: 1
    type: dword
```

## Scalability: when to split further

Profile vars use OS-family prefixes so each file carries values for one platform:

- `*_linux_*`:   consumed by all Linux builds (RHEL, Ubuntu, SLES)
- `*_windows_*`: consumed only by Windows builds

If RHEL and Ubuntu ever need **different** package lists for the same profile, replace `*_linux_*` with
`*_rhel_*` / `*_ubuntu_*` and update consumers.
