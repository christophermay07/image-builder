# windows_hardening

Applies Windows Server 2022 STIG via the Ansible Lockdown standalone role.

## What This Role Does

1. Installs profile-specific Windows features (if any)
2. Applies profile-specific registry/configuration changes (if any)
3. Runs the `win2022stig` role for STIG hardening
4. Runs Sysprep to generalize the image for AMI creation

Steps 1-2 are provider-agnostic. Step 3 is Ansible Lockdown-specific.

## STIG Provider: Ansible Lockdown

This role uses the [Ansible Lockdown](https://github.com/ansible-lockdown) standalone role
(`ansible-lockdown/Windows-2022-STIG`, installed as `win2022stig`) for STIG remediation. The coupling to Ansible
Lockdown exists in three places:

| Coupling point                | File                                     | What to change                            |
|-------------------------------|------------------------------------------|-------------------------------------------|
| `windows_stig_role` variable  | `defaults/main.yml`                      | Change the role name or replace the       |
|                               |                                          | `include_role` task entirely              |
| `win2022stig_rule_*` override | `defaults/main.yml`, group_vars,         | Remove Ansible Lockdown variables, add    |
| variables                     | host_vars                                | the new provider's equivalents            |
| Role requirement              | `requirements.yml`                       | Swap role source (Git URL or Galaxy)      |

> **Note:** `windows_compliance_scan` already uses PowerSTIG (not Ansible Lockdown) for post-hardening auditing. If
> remediation also moves to PowerSTIG, consider whether the two roles should be merged.

## Rule Tailoring

The Ansible Lockdown role exposes each STIG rule as a toggleable variable (e.g.,
`win2022stig_rule_XXXXXX_enabled: false`). These are native Ansible Lockdown variables, not variables owned by this
role.
Set them directly in `defaults/main.yml`, group_vars, or host_vars:

```yaml
win2022stig_rule_000001_enabled: false  # Reason: conflicts with X
```

The STIG role picks them up automatically from the Ansible variable namespace when included; no explicit `vars:`
pass-through is needed.

## Variables

| Variable                           | Default                       | Description                                     |
|------------------------------------|-------------------------------|-------------------------------------------------|
| `windows_stig_role`                | `win2022stig`                 | STIG role name (Ansible Lockdown)               |
| `profile_windows_extra_features`   | `[]`                          | Windows features to install (composed from base |
|                                    |                               | + profile-specific)                             |
| `profile_windows_registry_entries` | `{}`                          | Registry entries applied via win_regedit        |
|                                    |                               | (composed from base + profile-specific)         |

## Dependencies

Requires the `win2022stig` role (from `ansible-lockdown/Windows-2022-STIG`) installed via `requirements.yml`.
