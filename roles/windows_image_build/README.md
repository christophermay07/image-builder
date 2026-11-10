# windows_image_build

Builds Windows Server images using Packer with an Ansible provisioner.

Currently uses the Packer `amazon-ebs` builder for AWS AMIs. Future: will add `azure-arm` and `googlecompute` sources
for Azure and GCP.

## Execution Boundary: Outer Ansible, Packer, and Windows

**This role is the outer pipeline's entry point for hardening.** `build_windows.yml` includes `windows_image_build`,
which renders Packer configuration, copies provisioner playbooks, and runs Packer on a Linux builder via `delegate_to`.
It does not include `windows_hardening`.

Packer's `provisioner "ansible"` then launches a separate `ansible-playbook` process **on that Linux builder**.
The copied `<vm_name>-harden.yml` includes `windows_hardening`, which applies Windows modules to Packer's temporary
Windows guest over WinRM. Ansible and the role files stay on the builder; the guest executes the module code.
The scan and Sysprep provisioners use the same builder-side execution model.

The three provisioner playbooks are static YAML assets in `files/`, staged with `ansible.builtin.copy`.
Their settings arrive through separate variable payloads; the playbooks do not need Jinja rendering.
The provider preflight playbook is also copied from `files/`. Its `roles` entry resolves `windows_stig_role` from
`hardening.yml` during the child process's syntax check, so a missing provider fails before Packer starts a guest.

This role invokes `builder_ansible_prepare` to install a private Ansible environment and dependencies, copy current
project roles, and serialize selected settings. `packer_template_dir` becomes the unique workspace for this attempt.
The outer play removes it after validation and publication, including on failure. Standalone callers must arrange
that cleanup themselves. Logs and reports remain outside the workspace.
See the [handoff inputs](../builder_ansible_prepare/README.md) and
[hardening configuration](../windows_hardening/README.md#builder-dependencies-and-variable-boundary).

## What This Role Does

1. Templates a Packer HCL configuration from the source image
2. Templates a Packer variables file with profile-specific settings
3. Runs `packer init` to fetch required plugins
4. Runs `packer build` which:
   - Launches a cloud instance from the source image
   - Launches builder-side Ansible for hardening/customization of the Windows guest over WinRM
   - Runs a pre-seal PowerSTIG scan (build-time diagnostic)
   - Generalizes via Sysprep and captures the result as a new cloud image
5. Extracts the output image ID for distribution

After this role completes, `windows_ami_validate` boots a fresh instance from the
registered AMI and runs a post-AMI PowerSTIG scan to validate the shipped artifact.
See ADR-IB-031 for the rationale.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

The contract includes `packer_template_dir`, the password alias source, and optional derived builder settings.

Task-level checks of incoming hardening, profile, registry, and rule-toggle settings run before builder selection or
build facts are set. The provisioner playbook preflight runs after preparation because it checks the staged files
and installed dependencies in the private workspace.

## Variables

`windows_stig_overrides` accepts boolean provider toggles named `wnYY_XX_NNNNNN`, including `wn22_*` and `wn25_*`.
The version suffix is two digits, the rule prefix is two lowercase letters, and the rule number is six digits.
String values such as `"false"`, malformed names, and connection-variable overrides are rejected before preparation.

`windows_stig_role` and `powerstig_stig_id` are required from `group_vars/windows_*.yml`, with no release-specific
fallback. Both are validated before builder preparation. A 2025 build keeps its 2025 selections rather than silently
using 2022 settings. Its selected provider must also exist in `requirements.yml`; the current requirements install
only `win2022stig`, so the 2025 provider dependency still needs to be added and pinned before 2025 builds can run.

`packer_communicator` is read from the OS-family inventory and defaults to `winrm`. The Packer template consumes this
value, but the current Windows role accepts only `winrm`: its connection settings and bootstrap require WinRM.
Other values fail before builder preparation, dependency downloads, or guest creation.

### Defaults

| Variable                        | Default                          | Description                            |
|---------------------------------|----------------------------------|----------------------------------------|
| `packer_instance_type`          | `m5.xlarge`                      | EC2 instance type for build            |
| `packer_binary`                 | `/usr/local/bin/packer`          | Path to Packer binary (cross-role)     |
| `packer_template_dir`           | `{{ builder_work_dir }}/packer`  | Packer HCL template directory          |
| `packer_log_dir`                | `{{ builder_work_dir }}/logs`    | Packer log directory                   |
| `packer_winrm_username`         | `Administrator`                  | WinRM user for Packer provisioner      |
| `packer_winrm_password`         | `{{ winrm_admin_password }}`     | WinRM password (mapped from vault)     |
| `builder_work_dir`              | `/var/lib/image-builder`         | Base working directory (cross-role)    |
| `aws_region`                    | `us-east-1`                      | AWS region (cross-role)                |
| `aws_build_access_key_id`       | `""`                             | AWS access key for build operations    |
| `aws_build_secret_access_key`   | `""`                             | AWS secret key for build operations    |
| `aws_build_session_token`       | `""`                             | AWS session token for build operations |
| `packer_plugin_amazon_version`  | `1.8.3`                          | Exact Packer amazon plugin version     |
| `packer_plugin_ansible_version` | `1.1.6`                          | Exact Packer ansible plugin version    |
| `report_output_dir`             | `{{ builder_work_dir }}/reports` | Report output path (cross-role)        |

### Required from inventory (no default)

`ami_base_tags` is required from `inventory/group_vars/all.yml`; the Packer template renders its entries as AMI tags.
Its `build_timestamp` comes from the same shared inventory input used by export and release publication.

| Variable               | Inventory source      | Example                 |
|------------------------|-----------------------|-------------------------|
| `source_ami`           | `windows_*.yml`       | `ami-0123456789abcdef0` |
| `winrm_admin_password` | vault / extra-vars    | (secret)                |
| `os_family`            | `windows_targets.yml` | `windows`               |
| `os_version`           | `windows_*.yml`       | `2022`                  |
| `profile`              | `profile_*.yml`       | `base`                  |
| `builder_group`        | `all.yml` (derived)   | `builders_packer`       |
| `windows_stig_role`    | `windows_*.yml`       | `win2022stig`           |
| `powerstig_stig_id`    | `windows_*.yml`       | `WindowsServer-2022-MS` |

The assigned builder must also supply `builder_pip_packages` through its hostvars. The role normally replaces
`packer_template_dir` with the private workspace before use; an extra-var override takes precedence over that fact.
The password entry is an alias for the injected secret, and empty AWS key entries mean no explicit credential
override; they do not supply authentication.

### Azure / GCP (future, not yet in defaults)

Azure and GCP builders are placeholder. Variables will be added to
`defaults/main.yml` when those providers are implemented.

## Dependencies

Requires `builder_configure` to have installed Packer, Python 3.12, pip, and Git on the builder.
The builder must reach the configured Python/collection sources and public GitHub for the pinned STIG role.

The calling build play must first run `image_build_initialize`. The resulting `image_build_id`
is required. After Packer produces its AMI, this role records `cloud_image_result` with provider, native image ID,
source location, and current build ID. Post-AMI validation and publication use that common identity; a raw AMI fact
alone does not authorize distribution.

After `image_validation_gate`, the playbook calls the separate
[`windows_artifacts_prepare`](../windows_artifacts_prepare/README.md) role to generate build metadata and select the
six evidence files for `artifactory_upload`. Building stays in this role; preparation, upload, Release Bundle
creation, and native approval are explicit playbook stages.
