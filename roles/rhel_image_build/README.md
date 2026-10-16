# rhel_image_build

Builds RHEL images using RHEL Image Builder (osbuild-composer) with FIPS-enabled, STIG-hardened blueprints.

## What This Role Does

1. Renders a TOML blueprint from a Jinja template with FIPS, STIG, partition layout, cloud-init, and profile-specific
   packages
2. Pushes the blueprint to the builder's osbuild-composer service
3. Starts a compose and waits for it to complete
4. Downloads the resulting qcow2 image

## Blueprint Templates

- `rhel-blueprint.toml.j2`: shared blueprint for all RHEL major versions and profiles

OS and profile differences are handled via Jinja variables (`os_major`, `os_version`, `profile_linux_packages`, etc.)
composed from base + profile-specific layers in the inventory group_vars (see `all_profiles/`).

## How It Differs from the Former Kickstart Approach

- No ISOs needed; osbuild-composer uses RPM repos directly
- No KVM/virt-install; osbuild-composer builds internally
- FIPS and STIG are applied during the compose via blueprint customizations
- cloud-init datasource config is baked in via `[[customizations.files]]`
- The image is sealed by the compose process (no separate seal step)

## Variables

| Variable                  | Default                                | Description                                     |
|---------------------------|----------------------------------------|-------------------------------------------------|
| `compose_output_type`     | `qcow2`                                | Output format (qcow2, ami, vhd, gce)            |
| `compose_timeout_retries` | `120`                                  | Max poll iterations                             |
| `compose_poll_interval`   | `30`                                   | Seconds between polls                           |
| `image_version`           | CalVer `YYYY.MM.DD`                    | Version string in blueprint metadata            |
|                           |                                        | (auto-generated at runtime)                     |
| `image_version_suffix`    | `""`                                   | Optional suffix appended to the CalVer version  |
|                           |                                        | (see below)                                     |
| `builder_group`           | _(from method group_vars)_             | Builder group to delegate to                    |
| `blueprint_template`      | _(from family group_vars)_             | Template to use                                 |
| `profile_linux_packages`  | _(composed in all_profiles/linux.yml)_ | Extra packages (base + profile-specific)        |
| `stig_unselected_rules`   | `[]`                                   | STIG rules to deselect in tailoring             |
| `cloud_init_datasources`  | _(from method_osbuild.yml)_            | Datasource list for cloud-init                  |

## Image Versioning

By default, `image_version` is a CalVer string (`YYYY.MM.DD`) generated at runtime from the Ansible controller's
clock. Scheduled pipeline runs automatically get a unique version each day with no manual input.

When you need to distinguish multiple builds on the same day, set `image_version_suffix`:

```bash
# Dev iteration: append a manual sequence number
ansible-playbook playbooks/build_rhel.yml -e image_version_suffix=.2    # → 2026.10.06.2

# Prod rebuild: append the AAP job ID for traceability
# (in the AAP job template extra_vars)
image_version_suffix: ".{{ awx_job_id }}"                               # → 2026.10.06.4812
```

To bypass CalVer entirely, override `image_version` directly:

```bash
ansible-playbook playbooks/build_rhel.yml -e image_version=1.0.0
```

## Dependencies

None. Expects builder_configure to have already run.

## Manual Testing (Cockpit GUI)

This section is for ad-hoc testing or familiarization with the osbuild workflow. The automation handles all of these
steps and produces a release bundle with compliance reports; use it for real builds.

### Prerequisites

Install the Image Builder tooling and Cockpit on a RHEL 8 or 9 host:

```bash
sudo dnf install -y \
    osbuild-composer \
    composer-cli \
    cockpit \
    cockpit-composer

sudo dnf install -y \
    libguestfs-tools \
    openscap-scanner \
    openscap-utils \
    scap-security-guide
```

If you want to boot the image locally as a KVM guest, also install:

```bash
sudo dnf install -y qemu-kvm libvirt virt-install
```

### Enable Services

```bash
sudo systemctl enable --now osbuild-composer.socket
sudo systemctl enable --now cockpit.socket
```

If you installed KVM packages:

```bash
sudo systemctl enable --now libvirtd
```

Cockpit is then available at `https://<host>:9090`. The **Image Builder** menu appears when `cockpit-composer` is
installed.

### Push a Blueprint

The automation renders blueprints from the Jinja2 templates in `templates/`. For manual testing, either:

- Render the template yourself by filling in the variables (see the Variables table above), or
- Copy a `.toml` file from a prior automation run on the builder (look in `/var/lib/image-builder/blueprints/`).

Push the blueprint and verify it loaded:

```bash
composer-cli blueprints push my-blueprint.toml
composer-cli blueprints show my-blueprint
```

The `.toml` suffix is stripped from the name automatically.

### Start a Compose

From the CLI:

```bash
composer-cli compose start my-blueprint qcow2
```

Or use the Cockpit Image Builder GUI: select the blueprint, choose **QEMU Image (.qcow2)** as the output type, and
click **Create**.

Monitor progress:

```bash
composer-cli compose status
```

When the status shows **FINISHED**, download the image (note the UUID from the status output):

```bash
composer-cli compose image <UUID>
ls -l <UUID>-disk.qcow2
```

### RHEL 8 Post-Build Fix

**Only for RHEL 8 images built on a RHEL 9 host.** RHEL 9 builders inject `inode64` into tmpfs mount options and the
STIG profile adds a stale `/proc/cmdline` mount -- both break RHEL 8 at boot.

```bash
virt-edit -a <UUID>-disk.qcow2 /etc/fstab \
    -e 's/,inode64//; s/inode64,//; $_ = "" if m{\s/proc/cmdline\s}'
```

Skip this step for RHEL 9 images (inode64 is a valid default there).

### Offline Compliance Scan

Mount the image read-only and run an `oscap-chroot` scan to produce the same reports the automation generates:

```bash
sudo mkdir -p /mnt/image-scan
sudo guestmount -a <UUID>-disk.qcow2 -i --ro /mnt/image-scan

# RHEL 9
oscap-chroot /mnt/image-scan xccdf eval \
    --profile xccdf_org.ssgproject.content_profile_stig \
    --results oscap-results.xml \
    --report oscap-report.html \
    /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml

# RHEL 8: use ssg-rhel8-ds.xml instead

sudo guestunmount /mnt/image-scan
```

`oscap` returns exit code 2 when some rules are not applicable (expected for offline scans -- process checks, service
status, etc. require a running system). Exit code 0 means all rules passed; exit code 1 means an error.

### Optional: Boot as a Local KVM Guest

Move the image into the libvirt images directory and import it:

```bash
sudo mv <UUID>-disk.qcow2 /var/lib/libvirt/images/my-test-vm.qcow2

sudo virt-install \
    --name my-test-vm \
    --memory 2048 \
    --vcpus 2 \
    --disk /var/lib/libvirt/images/my-test-vm.qcow2 \
    --import \
    --os-variant rhel9.0 \
    --noautoconsole
```

Or use the Cockpit **Virtual Machines** page: click **Import VM**, select the qcow2 file, choose the correct OS
variant, and click **Import and run**.

> **Note:** Local KVM guests do not have access to a cloud metadata service, so cloud-init will fall back to the
> `NoCloud` datasource. To inject SSH keys or user-data locally, create a `cidata` seed ISO. For cloud deployments the
> automation handles this via the `cloud_convert` role (qcow2 -> AMI / VHD / GCP image).
