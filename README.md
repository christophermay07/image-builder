# Secure Image Builder

## Overview

This Ansible project builds hardened, FIPS-compliant, STIG-enforced VM images for deployment across multiple cloud
environments (AWS, Azure, GCP). It is designed to run on AAP 2.7, with builder instances running RHEL Image Builder
(osbuild-composer) for image creation. Builders run on EC2 and use a stop/start managed lifecycle; they are stopped
between pipeline runs and started automatically by the workflow. Azure and GCP builder infrastructure is planned.

The pipeline produces release bundles (image + compliance report) pushed to Artifactory, and converts images to
cloud-native formats for deployment.

## Supported Image Variants

The build matrix is **{OS versions} x {profiles}**:

| OS Version          | Build Method                     | Profiles     | Output (per profile)         |
|---------------------|----------------------------------|--------------|------------------------------|
| RHEL 8.10           | Image Builder (osbuild-composer) | base, poc    | qcow2 -> AMI, VHD, GCP image |
| RHEL 9.4            | Image Builder (osbuild-composer) | base, poc    | qcow2 -> AMI, VHD, GCP image |
| RHEL 9.6            | Image Builder (osbuild-composer) | base, poc    | qcow2 -> AMI, VHD, GCP image |
| RHEL 9.8            | Image Builder (osbuild-composer) | base, poc    | qcow2 -> AMI, VHD, GCP image |
| Windows Server 2022 | Packer (currently amazon-ebs)    | base, poc    | AMI (Azure/GCP planned)      |

**Total: 10 distinct image builds** (8 RHEL + 2 Windows). Each RHEL qcow2 is converted for 3 cloud vendors, producing
**24 RHEL cloud images + 2 Windows AMIs**.

## Architecture

### Build Methods

- **Image Builder (RHEL):** RHEL Image Builder (osbuild-composer) on an EC2 builder instance. A TOML blueprint defines
  packages, FIPS, STIG profile, partition layout, and cloud-init configuration. The compose produces a hardened qcow2
  directly; no ISOs, no KVM, no booting a guest VM.
- **Packer (Windows):** Packer with an Ansible provisioner handling STIG hardening and profile customization. Currently
  uses the amazon-ebs builder for AWS AMIs. Future: azure-arm and googlecompute builders for Azure/GCP.

### RHEL Build Pipeline

```
Blueprint TOML -> osbuild-composer compose -> qcow2
  -> offline FIPS verify + STIG scan (oscap-chroot)
  -> compress + metadata + Artifactory push
  -> cloud_convert (qcow2 -> AMI / VHD / GCP)
```

This is **Option A: Golden qcow2** - one compose per variant, producing a single qcow2 that is the source of truth.
Cloud-specific formats are derived from it. See [Output Format Options](#output-format-options) for the rationale and
how to switch to Option B if needed.

### Inventory Model

Build targets are modeled as phantom hosts in four group dimensions (OS family, OS version, profile, build method).
Each phantom host merges `group_vars` from all four dimensions. For the full model, variable placement rules, and
how-to recipes for adding new OS versions, profiles, or OS families, see [inventory/README.md](inventory/README.md).

### Builder Instances

The pipeline uses two EC2 builder instances (one for Image Builder, one for Packer), discovered by tags and managed
with a stop/start lifecycle.

### Hardening

- **FIPS:** Enabled at build time via `[customizations.fips]` in the blueprint. Verified post-compose by offline
  inspection of crypto-policies and kernel cmdline in the built image.
- **STIG (RHEL):** Applied during the compose via `[customizations.openscap]` in the blueprint with the DISA STIG
  profile. Blueprint tailoring (`[customizations.openscap.tailoring]`) allows rule-level overrides. Post-compose offline
  scan via `oscap-chroot` generates the compliance report included in the release bundle.
- **STIG (Windows):** Ansible Lockdown (`Windows-2022-STIG`) standalone role with per-rule toggleable variables.
  Two PowerSTIG scans: a pre-seal scan inside the Packer guest (build-time diagnostic) and a post-AMI validation scan
  against a fresh instance booted from the registered AMI (authoritative compliance evidence). See
  [WINDOWS-APPROACH.md](docs/WINDOWS-APPROACH.md) for why Windows needs two scans and RHEL needs one.
<!-- TODO: tailoring rules; initial versions need security team review -->

### Release Artifacts

Each successful build produces a release bundle pushed to Artifactory. The bundle contents differ by OS family
because RHEL and Windows use different build methods, compliance tools, and artifact formats.

**RHEL:**

- Golden qcow2 image (the single artifact of record; cloud formats are derived from it)
- OpenSCAP compliance report (XCCDF Results XML + HTML summary) from `oscap-chroot` offline scan
- FIPS mode confirmation (crypto-policies state is `FIPS` + `fips=1` kernel parameter)
- Build metadata (timestamp, compose UUID, STIG profile, builder ID)

**Windows:**

- Cloud image ID (currently AMI ID; the image stays in AWS)
- Pre-seal PowerSTIG scan results (JSON + HTML), labeled as build-time diagnostic
- Post-seal PowerSTIG scan results (JSON + HTML), labeled as authoritative compliance evidence for the
  shipped AMI
- FIPS policy flag check (`FIPSAlgorithmPolicy\Enabled` registry value from the post-AMI validation
  instance; reads the FIPS policy flag; this does not by itself confirm validated module use)
- Build metadata (AMI ID, source image, STIG role, timestamps)

<!-- TODO: define Artifactory repo path and naming convention -->
<!-- TODO: define metadata schema for release bundles -->

## Output Format Options

### Option A: Golden qcow2 + Convert (current)

This is the active configuration. Each RHEL variant produces one qcow2 via `composer-cli compose start <blueprint>
qcow2`. The qcow2 is the golden artifact pushed to Artifactory. The `cloud_convert` role then transforms it to AMI, VHD,
and GCP formats.

**Why this approach:**

- Single source of truth: one canonical artifact per variant
- Artifactory has the golden qcow2 for audit trail and archival
- 8 composes total (4 versions x 2 profiles); conversions are cheap
- Simpler compose management (one output type, consistent artifact naming)

**Trade-off:** qcow2-to-AMI via vmimport requires S3 staging and can take 30-60 minutes. The conversion step adds time
but is bounded.

### Option B: Direct Cloud Formats (alternative)

Instead of composing qcow2 and converting, run separate composes per cloud:

```bash
composer-cli compose start <blueprint> ami
composer-cli compose start <blueprint> vhd
composer-cli compose start <blueprint> gce
```

**What would change:**

- `compose_output_type` in `method_osbuild.yml` becomes a list (`compose_output_types: [ami, vhd, gce]`)
- `rhel_image_build` role loops over output types, running one compose each
- `cloud_convert` role is eliminated (no format conversion needed)
- Image Builder's `ami` / `vhd` / `gce` outputs are disk images in the native format, but you still need to upload and
  register them with the cloud provider (vmimport, `az image create`, `gcloud compute images create`)
- 24 composes for RHEL instead of 8 composes + 24 conversions
- No single golden artifact unless you also add a qcow2 compose (32 total)

**When to switch:** If vmimport wait times are unacceptable and you prefer to trade build parallelism for conversion
time. The composes can run in parallel on the builder if osbuild-composer is configured for concurrent builds.

**How to switch:**

1. Add `compose_output_types` list to `method_osbuild.yml`
2. Update `rhel_image_build/tasks/main.yml` to loop over output types
3. Update `image_export` to handle per-format artifact naming
4. Replace `cloud_convert` with `cloud_upload` (upload + register only)
5. Update `build-metadata.json.j2` to record the compose per format

## Usage

### Running from CLI

```bash
# Build everything
ansible-playbook playbooks/site.yml

# Build only RHEL 9 variants (all profiles)
ansible-playbook playbooks/build_rhel.yml --limit rhel9_targets

# Build a single image
ansible-playbook playbooks/build_rhel.yml --limit rhel-9.4-base

# Build all base profiles across all OS
ansible-playbook playbooks/site.yml --limit profile_base

# Build RHEL 9 x base only (intersection)
ansible-playbook playbooks/build_rhel.yml --limit 'rhel9_targets:&profile_base'
```

### Running from AAP

- **Job Templates:** Use the **Limit** field to select which variants to build.
- **Workflow Template:** "Image Build Pipeline" runs the full pipeline (start builders -> configure -> build RHEL +
  Windows in parallel -> distribute -> stop builders). Both build branches use `always_nodes` to reach Distribute, which
  waits for both to finish before running. Builders are stopped only after both branches complete. Individual image
  failures within a build are caught and reported at the end; one bad image doesn't prevent the rest from building.

<!-- TODO: document AAP URL and how operators access it -->

## Local Development

### Upgrading Ansible for Linting (Ubuntu)

The system-packaged Ansible on Ubuntu is often too old for `yamllint .` and `ansible-lint` to work correctly against
this project. The fix is to install a current Ansible in a Python virtual environment.

1. **Install Python 3.11** (and the venv module):

   ```bash
   sudo apt install python3.11 python3.11-venv
   ```

2. **Create a virtual environment** (the path can be anywhere you have write access, but a personal venv belongs in your
   home directory):

   ```bash
   python3.11 -m venv ~/.ansible-venv
   ```

3. **Activate it:**

   ```bash
   source ~/.ansible-venv/bin/activate
   ```

4. **Install/upgrade pip and the Ansible toolchain:**

   ```bash
   pip install --upgrade pip
   pip install ansible ansible-core ansible-lint yamllint
   ```

5. **Verify the version:**

   ```bash
   ansible --version
   ```

6. **Run the linters:**

   ```bash
   yamllint .
   ansible-lint
   ```

> **Note:** The virtual environment is only active in the shell session where you sourced it. If you open a new terminal
> or restart your shell, re-activate it with `source ~/.ansible-venv/bin/activate` before running Ansible or the
> linters.

## Credentials

All secrets are sourced from HashiCorp Vault; AAP pulls them at job launch via the "HashiCorp Vault Secret Lookup"
credential type. For Vault paths, AAP credential setup, IAM role separation, and the native-AAP fallback policy, see
[docs/CREDENTIALS.md](docs/CREDENTIALS.md). For cross-account AMI delivery, handoff contract options, and KMS
considerations, see [docs/AWS-IMAGE-DELIVERY.md](docs/AWS-IMAGE-DELIVERY.md).

## Inventory Quick Reference

Step-by-step recipes for adding new OS versions, profiles, and OS families to the build matrix are in
[inventory/README.md](inventory/README.md#quick-reference).

## RHEL 8 Caveats

RHEL 8 osbuild-composer has more limited customization support than RHEL 9:

- **Filesystem customizations** (`[[customizations.filesystem]]`): Requires osbuild-composer >= 62. Older versions on
  the builder may not support custom partition layouts; the compose will use the default layout.
- **OpenSCAP integration**: Available from RHEL 8.7+. The builder must run a recent enough osbuild-composer version to
  support `[customizations.openscap]`.

Verify osbuild-composer version on RHEL 8 builders before relying on filesystem or OpenSCAP blueprint features. If the
builder's version is too old, consider upgrading osbuild-composer or using a RHEL 9 builder to cross-build RHEL 8
images.

## Execution Environment

The custom EE includes:

- **Collections:** `amazon.aws`, `ansible.windows`, `community.general`, `community.windows`
- **Roles:** `win2022stig` (Ansible Lockdown Windows-2022-STIG, installed at project sync)
- **Python:** `boto3`, `botocore`, `pywinrm`
- **System:** `qemu-img`
- **Base image:** `ee-minimal-rhel9` from the Red Hat registry

Build with: `ansible-builder build -f execution-environment.yml -t image-builder-ee:latest`

<!-- TODO: EE registry URL (where built EE images are stored) -->
<!-- TODO: confirm base image availability
     (registry.redhat.io/ansible-automation-platform/ee-minimal-rhel9) -->

## Repository Structure

```
image-builder/
├── ansible.cfg                    # project-level Ansible config
├── .ansible-lint                  # linting rules
├── .yamllint                      # YAML formatting rules
├── requirements.yml               # collection dependencies
├── roles/
│   ├── builder_configure/         # configure builder (osbuild-composer, Packer)
│   ├── rhel_image_build/          # blueprint compose via composer-cli
│   ├── rhel8_fstab_fixup/         # post-compose fstab fixup for RHEL 8 on RHEL 9 builders
│   ├── rhel_hardening/            # offline FIPS verify + STIG scan
│   ├── cloud_init_prep/           # post-compose cloud-init tweaks (usually no-op)
│   ├── image_export/              # compress, bundle, Artifactory push (RHEL)
│   ├── cloud_convert/             # qcow2 -> AMI/VHD/GCP image conversion
│   ├── windows_image_build/       # Packer build with Ansible provisioner (currently amazon-ebs)
│   ├── windows_hardening/         # STIG via MindPoint Group collection (runs inside Packer guest)
│   ├── windows_compliance_scan/   # Pre-seal PowerSTIG scan (runs inside Packer guest; build diagnostic)
│   ├── windows_ami_validate/      # Post-AMI PowerSTIG scan (boots AMI; authoritative compliance evidence)
│   ├── image_release_publish/     # compliance artifact + metadata upload (Windows)
│   ├── artifactory_release_bundle/ # JFrog Release Bundle v2 create/sign (shared)
│   ├── image_distribute/          # Image distribution per cloud (AMI copy, Azure Gallery, GCP sharing)
│   └── ami_cleanup/               # AMI retention management (deregister + delete snapshots)
├── playbooks/
│   ├── site.yml                   # full pipeline orchestrator
│   ├── start_builders.yml         # start stopped builder EC2 instances
│   ├── refresh_inventory.yml      # re-scan aws_ec2.yml after starting builders (CLI only)
│   ├── configure_builders.yml     # builder host setup
│   ├── build_rhel.yml             # RHEL Image Builder pipeline
│   ├── build_windows.yml          # Windows AMI build pipeline
│   ├── distribute_images.yml      # image distribution
│   ├── cleanup_amis.yml           # AMI retention cleanup (on-demand / scheduled)
│   └── stop_builders.yml          # stop builder EC2 instances
├── inventory/
│   ├── README.md                  # inventory model + quick-reference recipes
│   ├── targets.yml                # phantom hosts + group structure
│   ├── aws_ec2.yml                # dynamic builder discovery
│   └── group_vars/                # per-group configuration
└── docs/
    ├── AWS-IMAGE-DELIVERY.md      # cross-account AMI delivery, handoff contract, KMS
    ├── CREDENTIALS.md             # Vault, IAM roles, signing, bootstrap exceptions
    └── ...                        # approach docs, ADRs, requirements, etc.
```

## Dependencies

| Dependency                    | Source                    | Purpose                                     |
|-------------------------------|---------------------------|---------------------------------------------|
| `amazon.aws` >= 11.0.0        | Automation Hub / Galaxy   | EC2 modules, aws_ec2 inventory plugin (AWS) |
| `ansible.windows` >= 3.7.0    | Automation Hub / Galaxy   | Windows module support                      |
| `community.general` >= 13.0.0 | Automation Hub / Galaxy   | General-purpose modules                     |
| `community.windows` >= 3.3.0  | Automation Hub / Galaxy   | Required by win2022stig role                |
| `Windows-2022-STIG` 2.9.0     | GitHub (ansible-lockdown) | Windows STIG role; installed via git in     |
|                               |                           | `requirements.yml` at AAP project sync      |
| `boto3` / `botocore`          | PyPI                      | AWS SDK for Python (AWS)                    |
| `pywinrm`                     | PyPI                      | WinRM connection plugin; needed on the      |
|                               |                           | builder host for Packer's Ansible           |
|                               |                           | provisioner (the EE copy does not help the  |
|                               |                           | Packer path)                                |
| `qemu-img`                    | System package            | Image format conversion                     |

## Future: Adding Ubuntu Support

See [Adding a New OS Family](inventory/README.md#adding-a-new-os-family-eg-ubuntu) for the structural checklist.
Ubuntu-specific implementation notes:

- **Build method:** `autoinstall` (cloud-init-based, not kickstart/anaconda). Could use Ubuntu's Image Builder
  equivalent or a virt-install autoinstall approach.
- **Install template:** `ubuntu2404-blueprint.toml.j2` (if using Image Builder) or `ubuntu2404.autoinstall.j2` in an
  `ubuntu_iso_build` role.
- **Hardening:** STIG/CIS remediation tooling TBD (oscap with Ubuntu SCAP content or Canonical's USG).
- **Reused roles:** `builder_configure`, `cloud_init_prep`, `image_export`, `cloud_convert`, `image_distribute` work
  as-is (they operate on qcow2 images regardless of OS).
