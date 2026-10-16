# rhel_hardening

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

## Variables

| Variable            | Default                            | Description                   |
|---------------------|------------------------------------|-------------------------------|
| `stig_profile`      | `xccdf_org...content_profile_stig` | XCCDF profile ID              |
| `stig_datastream`   | _(from family group_vars)_         | Datastream XML filename       |
| `report_output_dir` | `/var/lib/image-builder/reports`   | Where reports are saved       |
| `image_mount_point` | `/mnt/image-scan`                  | Temporary mount for the qcow2 |

## Dependencies

Requires `rhel_image_build` to have produced a qcow2 image.
Requires `libguestfs-tools`, `openscap-scanner`, and `scap-security-guide` on the builder host (installed by the
`builder_configure` role).
