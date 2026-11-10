# builder_ansible_prepare

Prepares isolated Ansible execution on the assigned Linux builder. This mechanism is independent of guest OS;
Windows is its first caller. It does not launch guests or choose their transport.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Optional workspace, executable-directory, and environment overrides are included in the contract.

Before allocating a workspace, guards check native dependency lists, payload mappings, runtime settings, and project
role directory names. Project role names must be simple basenames using letters, digits, underscores, dots, or hyphens.

## Inputs and outputs

`_builder_host` is an upstream fact set by the calling build role before `include_role`, following the same pattern
as other delegated roles. Standalone callers must supply this builder hostname explicitly.

The caller supplies `builder_work_dir` and lists of `builder_ansible_project_roles`, `builder_ansible_external_roles`,
`builder_ansible_collections`, and `builder_ansible_packages`.
`builder_ansible_project_roles` has no default and is required at role entry. An explicit empty list is also rejected.
Other empty dependency/payload collections skip their respective operations.
External role/collection entries use the normal project requirements format. Python packages use exact pip pins.
All external transitive role/collection dependencies must be listed explicitly; Galaxy runs with `--no-deps`.

`builder_ansible_payloads` maps simple file basenames to dictionaries of resolved configuration. The role writes one
restricted YAML file for each entry. The caller must select inputs explicitly and keep credentials out of payloads.
Project roles are copied from the controlling checkout's `roles/` directory.

The defaults use `/usr/bin/python3.12` and `ansible-core==2.19.11`. The builder must already have Python, pip, and Git.
The role returns `builder_ansible_workspace`, `builder_ansible_bin`, and `builder_ansible_environment` as host facts.
The controlled configuration excludes system collection discovery and enables no privilege escalation by default;
guest-specific playbooks can select their own escalation policy.

## Lifetime and dependencies

Every attempt creates a new private directory under `builder_work_dir`, including a dedicated Python environment.
This avoids shared dependency updates and concurrent content replacement at the cost of setup time and downloads.
Dependencies are version-pinned using the project requirements; pins are not cryptographic provenance verification.
Python transitive dependencies are resolved by pip; full hash-locked dependency sets remain a separate supply-chain
improvement. The core wheel digest is recorded in `.pinned_versions.yml` for audit, not enforced by pip installation.

The caller must keep the workspace through every provisioning/validation consumer and remove it in an `always`
block. The Windows outer play does this automatically. Reports and logs belong outside the workspace.
An abruptly killed job or unreachable builder can prevent cleanup; remove abandoned workspaces after confirming
that no build is using them. The role never removes arbitrary other build directories.

## Verification

The role verifies Python dependency compatibility and the presence of role entry points. Callers syntax-check their
staged playbooks and validate OS-specific settings before starting guests. Run the local integration tests with:

```shell
python3 -m unittest discover -s tests -p test_builder_handoff.py -v
```

These exercise typed payload transfer through real child Ansible processes, Linux role resolution without Windows
collections, override rejection, and cleanup on failure. They do not replace a live Packer canary build.
