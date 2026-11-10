# windows_hardening

Applies the Windows STIG provider selected for the target OS version. The current requirements install the
Ansible Lockdown Server 2022 role; other versions require their own pinned provider dependency.

## Who Calls This Role and Where It Runs

**`windows_hardening` is called by a separate Ansible process launched by Packer on the Linux builder.**
The outer AAP/CLI playbook never includes this role directly. The Windows guest receives and executes Windows module
code over WinRM; it does not run `ansible-playbook` or receive the role directory to execute locally.

```text
AAP execution environment / CLI (outer Ansible)
  playbooks/build_windows.yml: hosts = method_packer (phantom inventory targets)
    -> include_role: windows_image_build
    -> delegate file rendering and packer init/build to a Linux builders_packer host

Linux Packer builder
  packer build <vm_name>.pkr.hcl
    -> provisioner "ansible": launches a separate ansible-playbook process on this builder
    -> <vm_name>-harden.yml: hosts = all (Packer's temporary inventory of the Windows guest)
    -> role: windows_hardening
    -> include_role: windows_stig_role (required per-version selection)
         -> Windows module code executes on the temporary Windows guest over WinRM
```

The handoff is defined in these files:

1. [build_windows.yml](../../playbooks/build_windows.yml) includes `windows_image_build`.
2. [windows_image_build/tasks/main.yml](../windows_image_build/tasks/main.yml) renders the HCL and copies static
   provisioner playbooks onto `_builder_host`, then runs Packer there using `delegate_to`.
3. [windows-ami.pkr.hcl.j2](../windows_image_build/templates/windows-ami.pkr.hcl.j2) selects
   `<vm_name>-harden.yml` in its first `provisioner "ansible"` block, with `use_proxy = false`.
4. [windows-harden.yml](../windows_image_build/files/windows-harden.yml) supplies the actual
   `roles: [windows_hardening]` call. Its `hosts: all` targets Packer's guest inventory, not the outer phantom hosts.
5. [tasks/main.yml](tasks/main.yml) applies the profile settings and includes the STIG role.

Hardening therefore happens **during `packer build`**, before the pre-seal scan, report download, Sysprep, and AMI
capture. The later `windows_ami_validate` role is a separate outer pipeline step against a fresh instance from the AMI.
Adding `windows_hardening` to the outer play's role list would target the wrong inventory and bypass this lifecycle.

### Builder Dependencies and Variable Boundary

The inner Ansible process needs its own usable environment on the Linux builder: `ansible-playbook`, `pywinrm`,
`ansible.windows`, `community.windows`, this project's `windows_hardening` role, and the `win2022stig` role.
Installing dependencies in the AAP execution environment or at AAP project sync does not install them on the builder.
This is Packer's `ansible` provisioner, not `ansible-local`. See the
[HashiCorp provisioner reference](https://developer.hashicorp.com/packer/integrations/hashicorp/ansible/latest/components/provisioner/ansible).

`builder_configure` installs Python 3.12, pip, and Git on Packer builders. For each build,
`builder_ansible_prepare` creates a private workspace and Python environment, installs pinned Ansible and the project
requirements (including `win2022stig` version `2.9.0` from public GitHub), and copies project roles from the checkout.
The same workspace is used for post-AMI validation and removed by the outer play's `always` cleanup.
No dependency installation is required in the Windows guest for Ansible itself.

The outer run writes resolved profile features, registry entries, the provider name, and rule overrides into
`hardening.yml`. Packer loads it with `--extra-vars @<file>`. Scan and validation settings have separate files.
Only selected inputs cross this boundary; arbitrary outer inventory variables and facts are not forwarded.

Set rule toggles in the outer inventory using the explicit mapping:

```yaml
windows_stig_overrides:
  wn22_cc_000500: false
```

The contract accepts boolean `wnYY_XX_NNNNNN` rule toggles, where `YY` is a two-digit Windows version
(such as `22` or `25`), `XX` is a two-letter lowercase prefix, and `NNNNNN` is a six-digit rule number.
Connection variables and other names are rejected before guest creation. Setting a bare provider variable on the
outer phantom host does not forward it.
Provider defaults remain available within the staged role.

## What This Role Does

1. Installs profile-specific Windows features (if any)
2. Applies profile-specific registry/configuration changes (if any)
3. Runs the selected `windows_stig_role` for STIG hardening

Steps 1-2 are provider-agnostic. Step 3 is Ansible Lockdown-specific.
Sysprep belongs to the separate `windows-sysprep.yml` provisioner playbook, after scanning and report download.

## STIG Provider: Ansible Lockdown

This role uses the [Ansible Lockdown](https://github.com/ansible-lockdown) standalone role
(`ansible-lockdown/Windows-2022-STIG`, installed as `win2022stig`) for STIG remediation. The coupling to Ansible
Lockdown exists in three places:

| Coupling point               | File                             | What to change                          |
|------------------------------|----------------------------------|-----------------------------------------|
| `windows_stig_role` variable | Version group_vars               | Change the role name or replace the     |
|                              |                                  | `include_role` task entirely            |
| Provider rule overrides      | `defaults/main.yml`, group_vars, | Replace Ansible Lockdown variables with |
|                              | host_vars                        | the new provider's equivalents          |
| Role requirement             | `requirements.yml`               | Swap role source (Git URL or Galaxy)    |

> **Note:** `windows_compliance_scan` already uses PowerSTIG (not Ansible Lockdown) for post-hardening auditing. If
> remediation also moves to PowerSTIG, consider whether the two roles should be merged.

## Rule Tailoring

Use the rule toggle names documented by the pinned Ansible Lockdown role. Set them in `windows_stig_overrides`
in outer group_vars, host_vars, or extra-vars. They are expanded into the inner provider's variable namespace.
See [Builder Dependencies and Variable Boundary](#builder-dependencies-and-variable-boundary) for an example.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Before changing the guest, guards require a native feature list, a registry mapping, and non-empty registry paths.

## Variables

| Variable                           | Default  | Description                                     |
|------------------------------------|----------|-------------------------------------------------|
| `profile_windows_extra_features`   | `[]`     | Windows features to install (composed from base |
|                                    |          | + profile-specific)                             |
| `profile_windows_registry_entries` | `{}`     | Registry entries applied via win_regedit        |
|                                    |          | (composed from base + profile-specific)         |

### Required from inventory or caller (no default)

| Variable            | Inventory source | Example       |
|---------------------|------------------|---------------|
| `windows_stig_role` | `windows_*.yml`  | `win2022stig` |

## Dependencies

Requires the selected provider to be installed. Currently `win2022stig` comes from
`ansible-lockdown/Windows-2022-STIG`, pinned in
[requirements.yml](../../requirements.yml). Standalone callers must supply `windows_stig_role` explicitly.
See [Builder Dependencies and Variable Boundary](#builder-dependencies-and-variable-boundary).
