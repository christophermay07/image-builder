# all_profiles: common profile configuration

Variables in this directory are inherited by **every** profile.
Per-profile overlays live in `group_vars/profile_*.yml`.

## How composition works

| Prefix                | Purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `_base_*`             | Base config shared by every profile (defined here).                     |
| `_profile_specific_*` | Per-profile additions (default `[]` here, overridden in profile files). |
| `profile_*`           | Final composed value (Jinja expression, consumed by roles/templates).   |

Ansible evaluates the Jinja expressions lazily using each host's resolved variable values, so child-group
overrides in `profile_poc.yml` etc. are picked up automatically.

## YAML syntax notes for editors

**Lists:** `[]` means "empty list." When adding items, DELETE the `[]` and use block sequence syntax (`- item`)
on the following lines. Example:

```yaml
# BEFORE:
_base_linux_packages: []

# AFTER:
_base_linux_packages:
  - tuned-profiles-poc
  - compat-poc-c++-12
```

**Dicts:** `{}` means "empty dict." When adding entries, DELETE the `{}` and put the key/value mappings on the
following lines (indented). Example:

```yaml
# BEFORE:
_base_windows_registry_entries: {}

# AFTER:
_base_windows_registry_entries:
  poc_memory_management:
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
