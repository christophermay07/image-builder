# Ubuntu Support - Implementation Deltas

> [!CAUTION]
> This document is a **not a validated implementation plan.** It was written to capture design considerations and likely
> deltas from the RHEL path, but the team that wrote it will not be performing the Ubuntu implementation. If you are
> picking this up, please treat every recommendation as a starting point that requires your own validation. Assumptions
> may be incomplete, tool versions may have changed, and there will be considerations specific to your environment that
> this document does not address.

This document captures what is **genuinely different** about adding Ubuntu to the image build factory. It does not
repeat the standard inventory/profile wiring that applies to any new OS family; see
[inventory/README.md](../inventory/README.md) for that. Everything below is a delta from the RHEL path.

---

## Build Toolchain

RHEL images use `osbuild-composer` (Image Builder), which is a Red Hat product that only targets RHEL. Ubuntu has no
equivalent single-command image composer.

**Likely replacement:** [Packer](https://www.packer.io/) with an Ansible provisioner; the same pattern used for
Windows today. Packer launches a temporary EC2 instance from a Canonical-published Ubuntu AMI, provisions it via SSH,
then snapshots the result. This means Ubuntu builds would use `method_packer` (Dimension 4) rather than introducing a
third build method.

**Alternative:** Canonical's [ubuntu-image](https://github.com/canonical/ubuntu-image) tool, which builds disk images
from model assertions or classic definitions. It is closer in spirit to `osbuild-composer` (build without booting), but
it is less mature for cloud-image production and has no built-in SCAP integration. Evaluate whether its constraints are
worth the benefit of avoiding a guest VM.

| Concern           | RHEL (osbuild-composer)             | Ubuntu (likely Packer)                           |
|-------------------|-------------------------------------|--------------------------------------------------|
| Build mechanism   | Compose from blueprint, no guest VM | Launch guest VM, provision, snapshot             |
| Builder type      | Dedicated osbuild builder           | Shared with Windows Packer builder, or dedicated |
| Connection plugin | N/A (no SSH to guest)               | SSH (not WinRM)                                  |
| Guest networking  | Not needed                          | Required (Packer SSH)                            |

## STIG and Compliance

### Hardening

RHEL uses OpenSCAP remediation baked into the `osbuild-composer` blueprint (`[customizations.openscap]`). This is a
Red Hat-specific integration; Ubuntu does not have it.

For Ubuntu, STIG hardening would need to happen via Ansible during the Packer provisioning step, similar to how
Windows uses the MindPoint Group STIG collection. The Ubuntu equivalent:

- **Canonical's Ubuntu Security Guide (USG):** `apt install ubuntu-advantage-tools` → `sudo ua enable usg` on Ubuntu
  Pro, then use `usg fix` to apply CIS or DISA STIG profiles. However, USG requires Ubuntu Pro entitlement and runs
  on a live system, so it fits the Packer model but not an offline build.
- **ComplianceAsCode / SCAP Security Guide (SSG):** The open-source `scap-security-guide` package includes Ubuntu
  content (`ssg-ubuntu2204-ds.xml`). An Ansible role could run `oscap xccdf eval --remediate` against the STIG
  profile during the Packer build. This is the closest analog to the RHEL approach.

**Key difference:** On RHEL, STIG is applied pre-first-boot by Image Builder. On Ubuntu via Packer, STIG is applied
post-boot during provisioning. The image is unhardened for the duration of the Packer build, then hardened, then
snapshotted. This matches the Windows model.

### Audit / Compliance Scanning

RHEL uses `oscap-chroot` for offline scanning of the qcow2. Ubuntu could use the same tool (`openscap-scanner` is
available as an apt package), but the datastream is different:

| OS     | Datastream                           | Source package                                  |
|--------|--------------------------------------|-------------------------------------------------|
| RHEL   | `ssg-rhelN-ds.xml`                   | `scap-security-guide` (RPM)                     |
| Ubuntu | `ssg-ubuntu2204-ds.xml` (or similar) | `ssg-debderived` or `scap-security-guide` (apt) |

Whether offline `oscap-chroot` scanning works on a Packer-produced AMI snapshot (vs. a qcow2) is an open question.
Packer produces an AMI directly; to scan offline, you would need to either:

1. Export the AMI to a snapshot, create a volume, and mount it (more complex than guestmounting a qcow2).
2. Run the compliance scan live during the Packer build (post-hardening, pre-snapshot); simpler, but the scan happens
   on a running system, not the final artifact.

Option 2 is how Windows works today (PowerSTIG runs during the Packer build). It is pragmatic but means the scan result
describes the running builder guest, not the snapshotted image.

## FIPS

RHEL enables FIPS at compose time via `[customizations] fips = true` in the blueprint. This is atomic and guaranteed.

Ubuntu FIPS requires Ubuntu Pro (or Ubuntu FIPS-certified images from AWS Marketplace). Enabling FIPS on Ubuntu:

```bash
sudo ua enable fips        # or fips-updates
sudo reboot                # FIPS requires a reboot to take effect
```

This fits the Packer model (the guest can reboot during provisioning), but it introduces a dependency on Ubuntu Pro
licensing and the `ua` client. The builder's guest instance must be enrolled in Ubuntu Pro before FIPS can be enabled.

**Open question:** Does author have Ubuntu Pro entitlements? Without them, FIPS support is not available. This is
a fundamentally different licensing model from RHEL, where FIPS is a built-in kernel feature.

## Cloud Format Conversion

RHEL builds a qcow2, then converts to AMI/VHD/GCP image. Packer-built Ubuntu images (like Packer-built Windows images)
produce cloud-native artifacts directly (an AMI if building in AWS). The `cloud_convert` role would be skipped for
Ubuntu, same as Windows.

If multi-cloud output is needed from a single Ubuntu build, the pipeline would need to either:

- Run Packer separately in each cloud (one build per cloud), or
- Build in AWS, export the AMI to a raw/qcow2 format, and then use `qemu-img` + the RHEL-style conversion pipeline.

The first option is simpler; the second reuses existing code but adds an export step that does not exist today.

## Package Management

RHEL uses `dnf` / RPM repos; Ubuntu uses `apt` / Debian repos. Every role that installs packages or manages
repositories needs an Ubuntu code path. Roles that are already factored by OS family (`when: os_family == 'redhat'`)
need a matching `when: os_family == 'debian'` block.

Content sourcing is also different: RHEL content may come from Red Hat CDN, Satellite, or an Artifactory RPM remote.
Ubuntu content comes from Canonical's archive or an Artifactory Debian remote. The Artifactory repository layout
(R1 in OPEN-REQUIREMENTS.md) would need a Debian/Ubuntu equivalent.

## Subscription and Entitlement

|                  | RHEL                                          | Ubuntu                                            |
|------------------|-----------------------------------------------|---------------------------------------------------|
| Base OS access   | Red Hat subscription (CDN, Satellite, or SCA) | Free (Ubuntu Server), or Ubuntu Pro for           |
|                  |                                               | security/FIPS                                     |
| FIPS             | Included in base RHEL                         | Requires Ubuntu Pro                               |
| STIG content     | `scap-security-guide` RPM (free, open-source) | `scap-security-guide` apt (free, open-source)     |
| Extended support | ELS (paid add-on)                             | Ubuntu Pro (paid; includes ESM, FIPS, USG)        |

If FIPS or CIS/STIG-certified content is required, Ubuntu Pro licensing must be in place before Ubuntu builds can
start. This is a new procurement/entitlement dependency that does not exist for RHEL.

## Summary of New Work

| Area             | What's needed                                                              |
|------------------|----------------------------------------------------------------------------|
| Build method     | Packer + Ansible provisioner (reuse Windows pattern, swap WinRM for SSH)   |
| STIG hardening   | Ansible role using `oscap remediate` or USG against Ubuntu STIG datastream |
| STIG audit       | In-build scan (like Windows) or post-build AMI mount + `oscap-chroot`      |
| FIPS             | Ubuntu Pro enrollment + `ua enable fips` during Packer build               |
| Package roles    | `apt`-based code paths in any role that installs packages                  |
| Content sourcing | Artifactory Debian remote repository (new repo type)                       |
| Entitlement      | Ubuntu Pro subscription if FIPS is required                                |
| Builder          | Decide: share the Packer builder, or dedicate a third builder type         |
