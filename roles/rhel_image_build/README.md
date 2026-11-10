# rhel_image_build

Builds RHEL images using RHEL Image Builder (osbuild-composer) with FIPS-enabled, STIG-hardened blueprints.

## What This Role Does

1. Pushes build-time yum sources to osbuild-composer (if any are defined)
2. Renders a TOML blueprint from a Jinja template with FIPS, STIG, partition layout, cloud-init, repos, and
   profile-specific packages
3. Pushes the blueprint to the builder's osbuild-composer service
4. Starts a compose and waits for it to complete
5. Downloads the resulting qcow2 image

## Blueprint Templates

- `rhel-blueprint.toml.j2`: shared blueprint for all RHEL major versions and profiles

OS and profile differences are handled via Jinja variables (`os_version`, `profile_linux_packages`, etc.)
composed from base + profile-specific layers in the inventory group_vars (see `all_profiles/`). Yum repositories are
filtered by `os_major` so each image gets only version-appropriate repos. Both `build_yum_sources` and
`blueprint_yum_repos` are composed from base + profile-specific layers (same pattern as packages and services).

## Yum Repositories

Every RHEL image gets yum repos through two parallel mechanisms, both fed by the same composed variable
(`build_yum_sources`):

### Build-time sources (available during the compose)

Pushed to osbuild-composer via `composer-cli sources add` before the compose starts. Packages in the
blueprint's `[[packages]]` section can be installed from these repos. These sources are **not** present in
the final image.

Handled by: `tasks/manage_build_sources.yml` and `templates/osbuild-source.toml.j2`

### Final-image repos (baked into the image)

Rendered as `[[customizations.repositories]]` blocks in the blueprint TOML. These become `.repo` files in
`/etc/yum.repos.d/` so deployed systems can `dnf install` from them.

Handled by: the repo loop at the end of `templates/rhel-blueprint.toml.j2`

### How the repo list is composed

The `build_yum_sources` variable is built from three layers, each from a different inventory dimension:

```
build_yum_sources = _base_build_yum_sources               (all_profiles/linux.yml)
                  + _profile_specific_build_yum_sources    (profile_*.yml)
                  + _cloud_build_yum_sources               (cloud_*.yml)
```

`blueprint_yum_repos` currently aliases `build_yum_sources` (both lists are the same). If they need to
diverge, the comment in `linux.yml` explains how to restore a separate composition.

### os_major filtering

Each repo entry can optionally set `os_major` to restrict it to specific RHEL major versions. This supports
both a single value (`os_major: "9"`) and a list (`os_major: ["8", "9"]`). Repos without `os_major` apply
to all versions. This is used for EUS repos that exist on RHEL 8 and 9 but not 10.

### Shared settings

All repo entries reference two shared variables from `rhel_targets.yml`:

- `yum_repo_base_url`: mirror hostname/path used in every `baseurl`
- `yum_repo_gpgkey`: GPG key URL used in every `gpgkey`

Changing either one propagates to every repo in every profile and cloud. Per-entry overrides are still
possible since each entry has its own `gpgkey` field.

The role's empty helper defaults are valid when selected repositories do not reference them. Repositories using
these helpers require a usable mirror location and signing key URL from inventory.

## How It Differs from Kickstart Approach

- No ISOs needed; osbuild-composer uses RPM repos directly
- No KVM/virt-install; osbuild-composer builds internally
- FIPS and STIG are applied during the compose via blueprint customizations
- cloud-init datasource config and optional extra config files are baked in via `[[customizations.files]]`
- The image is sealed by the compose process (no separate seal step)

### Extra cloud-init configuration

Set `cloud_init_extra_configs` (default `[]`) in profile group_vars, host_vars, or AAP extra variables:

```yaml
cloud_init_extra_configs:
  - filename: 98-timezone.cfg
    content: |
      timezone: Etc/UTC
```

Each entry writes its complete `content` to `/etc/cloud/cloud.cfg.d/<filename>` with mode `0644` during composition.
Use `.cfg` basenames. Repeated filenames use the last entry; `99-datasources.cfg` replaces the generated datasource
file.
The settings are inputs for cloud-init when the deployed instance boots; the build does not execute cloud-init.

This replaces the former `cloud_init_prep` role and its mount/unmount step. The input format is unchanged;
`cloud_init_mount_point` is no longer used. Changes now require a new compose (`--tags build` or `--tags compose`);
the separate `cloud-init` tag is removed. Extra files are now included in the image assessed by the offline compliance
scan, rather than injected after scanning. Verify their final contents after compose-time OpenSCAP remediation.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Repository URL sources and optional builder, target-name, and compose-identifier overrides are also checked.

Compose polling settings must be positive integers. Repository version filtering requires `os_major`.

Before selecting a builder or changing composer sources, guards check native profile collections, extra cloud-init
files, and repository definitions. Extra filenames must be .cfg basenames. Repository IDs use letters, digits,
underscores, dots, colons, or hyphens and start with a letter, digit, or underscore; base URLs must be non-empty.

## Variables

### Defaults

| Variable                          | Default                               | Description                             |
|-----------------------------------|---------------------------------------|-----------------------------------------|
| `compose_output_type`             | `qcow2`                               | Output format (qcow2, ami, vhd, gce)    |
| `compose_timeout_retries`         | `120`                                 | Max poll iterations (120 x 30s = 60m)   |
| `compose_poll_interval`           | `30`                                  | Seconds between polls                   |
| `image_version`                   | CalVer `YYYY.M.D` (runtime)           | Version string in blueprint metadata    |
| `image_version_suffix`            | `""`                                  | Suffix appended to CalVer (see below)   |
| `stig_content_dir`                | `/usr/share/xml/scap/ssg/content`     | SCAP datastream directory               |
| `profile_linux_packages`          | `[]`                                  | Extra packages (base + profile layers)  |
| `profile_linux_enabled_services`  | `[]`                                  | Services to enable in blueprint         |
| `profile_linux_disabled_services` | `[]`                                  | Services to disable in blueprint        |
| `blueprint_filesystem_layout`     | `{}`                                  | Custom partition layout for blueprint   |
| `stig_unselected_rules`           | `[]`                                  | STIG rules to deselect in tailoring     |
| `stig_selected_rules`             | `[]`                                  | Extra STIG rules beyond base profile    |
| `builder_work_dir`                | `/var/lib/image-builder`              | Base working directory (cross-role)     |
| `blueprint_dir`                   | `{{ builder_work_dir }}/blueprints`   | Rendered blueprint directory            |
| `image_output_dir`                | `{{ builder_work_dir }}/output`       | Built-image output path (cross-role)    |
| `cloud_init_datasources`          | `['NoCloud']`                         | Datasource list for cloud-init          |
| `build_yum_sources`               | `[]`                                  | Build-time repos (base+profile+cloud)   |
| `blueprint_yum_repos`             | `[]`                                  | Final-image repos (= build_yum_sources) |
| `stig_profile`                    | `xccdf_org.ssgproject...profile_stig` | XCCDF profile ID (cross-role)           |

### Required from inventory (no default)

| Variable             | Inventory source    | Example                  |
|----------------------|---------------------|--------------------------|
| `blueprint_template` | `rhel_targets.yml`  | `rhel-blueprint.toml.j2` |
| `os_version`         | `rhel_*_*.yml`      | `9.4`                    |
| `profile`            | `profile_*.yml`     | `base`                   |
| `stig_datastream`    | `rhel_targets.yml`  | derived from `os_major`  |
| `builder_group`      | `all.yml` (derived) | `builders_osbuild`       |

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

## Artifact preparation

After cloud validation and `image_validation_gate`, the playbook calls the separate
[`rhel_artifacts_prepare`](../rhel_artifacts_prepare/README.md) role. It verifies the prepared qcow2 checksum,
generates build metadata, and selects the qcow2, OpenSCAP HTML/XML, and metadata files for `artifactory_upload`.
Composition stays in this role; preparation, upload, JFrog bundling, and native approval are explicit playbook stages.
