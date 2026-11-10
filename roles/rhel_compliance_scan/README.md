# rhel_compliance_scan

Validates FIPS configuration and runs an offline STIG compliance scan against built RHEL images.

## What This Role Does

1. **FIPS Verification (offline):** Mounts the qcow2 image read-only and checks that crypto-policies are set to FIPS
   and `fips=1` is in the kernel parameters. No need to boot the image.
2. **Compliance Scan (offline):** Runs `oscap-chroot` against the mounted image filesystem to validate STIG compliance.
   Generates HTML and XML reports for the release bundle.

## How Hardening Works

STIG remediation is applied by RHEL Image Builder during the compose via `[customizations.openscap]` in the blueprint.
This role does not perform remediation; it validates the result.

Some STIG rules will report "not applicable" or "not checked" in the offline scan because they require a running system
(e.g., process checks, service status, network tests). This is expected; the full set of controls is evaluated by the
Image Builder's pre-first-boot remediation pass.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Optional target-name, derived image-path, and generated scan-command overrides are included in the contract.

Before mounting the image, guards require usable builder, STIG, mount, and output settings and verify that the image
is a regular file. Image checks follow symlinks and skip checksum calculation.

## Variables

### Defaults

| Variable            | Default                                   | Description                          |
|---------------------|-------------------------------------------|--------------------------------------|
| `stig_content_dir`  | `/usr/share/xml/scap/ssg/content`         | SCAP datastream directory            |
| `stig_profile`      | `xccdf_org.ssgproject...profile_stig`     | XCCDF profile ID (cross-role)        |
| `image_mount_point` | `/mnt/image-scan`                         | Temporary mount for the qcow2        |
| `builder_work_dir`  | `/var/lib/image-builder`                  | Base working directory (cross-role)  |
| `report_output_dir` | `{{ builder_work_dir }}/reports`          | Where reports are saved (cross-role) |
| `image_output_dir`  | `{{ builder_work_dir }}/output`           | Built-image path (cross-role)        |

### Required from inventory (no default)

| Variable          | Inventory source   | Example                   |
|-------------------|--------------------|---------------------------|
| `stig_datastream` | `rhel_targets.yml` | derived from `os_major`   |

### Upstream facts (set by earlier roles)

| Variable         | Set by             |
|------------------|--------------------|
| `_builder_host`  | `rhel_image_build` |

## Future: Online Scan

The current scan is offline (`oscap-chroot` against a mounted filesystem). This is fast and avoids booting the image,
but some STIG rules cannot be evaluated offline because they inspect running processes, active services, network
sockets, or kernel runtime state. Those rules report "not applicable" or "not checked."

An online scan would close that gap. At a high level it would require:

1. **Boot the qcow2 as a VM.** Use `cloud_convert` to register an AMI (or equivalent), launch a temporary instance,
   and wait for SSH. The RHEL pipeline dispatches guest SSH smoke testing through `cloud_validate` (AWS implemented).
   Windows also has post-AMI validation (`windows_ami_validate`).
2. **Run `oscap` on the live guest.** Either SSH in and run `oscap xccdf eval` directly, or use
   `community.general.openscap` if a suitable Ansible module is available. The same `stig_profile` and
   `stig_datastream` variables apply.
3. **Collect and merge results.** Download the XML/HTML reports to the builder host under `report_output_dir`, prefixed
   `post-boot-` to distinguish them from the offline `oscap-chroot` results.
4. **Tear down the instance.** Terminate the temporary VM unconditionally (even on scan failure), mirroring the
   cleanup logic in `windows_ami_validate`.

The offline scan should remain as a fast pre-check. The online scan would run after `cloud_convert` and before
`artifactory_upload`, producing the authoritative compliance evidence.

## Dependencies

Requires `rhel_image_build` to have produced a qcow2 image.
Requires `libguestfs-tools`, `openscap-scanner`, and `scap-security-guide` on the builder host (installed by the
`builder_configure` role).
