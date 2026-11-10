# rhel8_fstab_fixup

Patches `/etc/fstab` inside RHEL 8 qcow2 images after the osbuild-composer compose to fix boot-breaking entries
introduced by STIG remediation. **This role is RHEL 8-specific and should be retired when RHEL 8 support is dropped.**
RHEL 9+ images are not affected.

## What This Role Does

Uses `virt-edit` to make two surgical fixes to `/etc/fstab` in the sealed qcow2:

1. **Strips `inode64` from tmpfs mount options.** RHEL 9 builders default `inode64` on tmpfs mounts. RHEL 8 kernels do
   not understand the option, so the image fails to boot.
2. **Removes a stale `/proc/cmdline` tmpfs mount.** The STIG remediation copies this entry from the builder host's live
   mount table into the image's fstab. The mount does not exist on the target system, so it breaks boot.

Only runs when `os_version < 9`.

## Why virt-edit (and Not the Blueprint)

`virt-edit` is a last resort for modifying a composed image. The pipeline's preferred tools, in order, are:

1. Blueprint customizations (`[[customizations.files]]`, `[[customizations.filesystem]]`, etc.)
2. STIG tailoring (`stig_unselected_rules`)
3. `guestmount` (read-write access to the guest filesystem)
4. `virt-customize --run-command` (chroot-like script execution)

None of these work for this specific problem:

- **Blueprint file injection runs before STIG remediation.** osbuild-composer applies `[customizations.openscap]`
  remediation as the last stage of the compose. Any `/etc/fstab` content written via `[[customizations.files]]` or RPM
  `%post` scriptlets is overwritten by the STIG pass. There is no post-remediation hook in osbuild-composer.
- **STIG tailoring would leave controls unaddressed.** The STIG rules that produce these fstab entries are
  legitimate security controls (tmpfs mount hardening). Deselecting them to avoid the side effect means the
  controls are not remediated at all, which is not acceptable for compliance.
- **inode64 comes from the RHEL 9 builder's kernel defaults.** RHEL 9 kernels default `inode64` on tmpfs;
  osbuild-composer inherits this when generating fstab entries for the target. RHEL 8 kernels don't
  understand the option. Building on a RHEL 8 builder would avoid this problem, but not the next one.
- **The `/proc/cmdline` entry comes from the builder's live mount table.** The STIG remediation inspects
  the builder's mounts and copies a `/proc/cmdline` tmpfs entry into the image's fstab. That mount doesn't
  exist on the target system. This happens regardless of the builder's OS version; any builder with a
  `/proc/cmdline` tmpfs mount (from systemd or its own STIG hardening) will contaminate the image.

The ideal fix is upstream in `scap-security-guide`: the remediation should generate fstab entries appropriate
for the target OS, not copy mount state from the builder host. Until that upstream fix exists, `virt-edit`
after the compose is the only option.

For the full decision hierarchy on post-compose modifications, see
[PACKER-POST-COMPOSE-STEP.md](../../docs/PACKER-POST-COMPOSE-STEP.md).

## Do Not Extend This Pattern

This role exists solely for RHEL 8. It is not a template for future OS versions.

RHEL 9+ images do not have these issues: `inode64` is a valid default on RHEL 9 kernels, and the RHEL 9 STIG
remediation does not produce the stale `/proc/cmdline` entry. If a similar compose-time contamination problem
appears on a future OS version, address it by:

1. Filing an upstream bug against `scap-security-guide`.
2. Using STIG tailoring (`stig_unselected_rules`) if the rule can be compensated for elsewhere.
3. Using `guestmount` or `virt-customize` if the fix can be applied without conflicting with STIG ordering.

Do not create a `rhel9_fstab_fixup` or similar role. If none of the above options work, escalate the issue
for architectural review before reaching for `virt-edit`.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Shared path defaults and optional target-name overrides are included in the contract.

For RHEL 8, guards check the assigned builder and input directory, then verify the image file before editing it.
These checks are skipped alongside the edit for RHEL 9 and later.

## Variables

### Defaults

| Variable           | Default                         | Description                          |
|--------------------|---------------------------------|--------------------------------------|
| `builder_work_dir` | `/var/lib/image-builder`        | Base working directory (cross-role)  |
| `image_output_dir` | `{{ builder_work_dir }}/output` | Built-image output path (cross-role) |

### Required from inventory (no default)

| Variable     | Inventory source | Example |
|--------------|------------------|---------|
| `os_version` | `rhel_*_*.yml`   | `8.10`  |

### Upstream facts (set by earlier roles)

| Variable        | Set by             |
|-----------------|--------------------|
| `_builder_host` | `rhel_image_build` |

## Dependencies

Requires `rhel_image_build` to have produced a qcow2 image. Requires `libguestfs-tools` on the builder
(installed by `builder_configure` as part of `validation_packages`).
