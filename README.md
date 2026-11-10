# Secure Image Builder

## Overview

This Ansible project builds hardened, FIPS-compliant, STIG-enforced VM images for deployment across multiple cloud
environments (AWS, Azure, GCP). It is designed to run on AAP 2.7, with ephemeral EC2 builder instances provisioned at
pipeline start and terminated when the run finishes. The Ansible control plane (AAP controller and builder instances)
always runs on EC2. How images reach each cloud depends on the build method:

- **osbuild (RHEL):** produces a qcow2 on the EC2 builder, then `cloud_convert` transforms it to the target cloud
  format (AMI, VHD, GCP image). The build itself is cloud-agnostic.
- **packer (Windows):** the Packer builder plugin runs natively on the target cloud (e.g., `amazon-ebs` for AWS,
  `azure-arm` for Azure, `googlecompute` for GCP). The EC2 builder orchestrates Packer, but the guest VM and resulting
  image live on the target cloud.

The ephemeral model provisions one builder instance per image target (1:1). If the pipeline is building 10 RHEL images
and 2 Windows images, it spins up 10 osbuild builders and 2 packer builders, each runs a single build, and all are
terminated when the run finishes. No round-robin, no serial batching, no idle builders waiting for work.

Each build produces a release bundle pushed to Artifactory. For RHEL, the bundle includes the golden qcow2 image,
compliance reports, and build metadata. Every RHEL target must register a native cloud image and pass an SSH smoke
test before publication. AWS is implemented; Azure/GCP have explicit TODO handlers that block publication.
For Windows, the cloud image stays in the cloud provider
(e.g., AMI in AWS); the bundle contains compliance evidence, the image ID, and build metadata.

> **v1 note:** The v1 pipeline uses persistent builders with a stop/start lifecycle instead of true 1:1 ephemeral
> instances. A small fixed pool of builders (typically one per type) is stopped between runs and started by the
> workflow; image targets are round-robined across available builders with serial batching. The ephemeral pipeline
> (`site_ephemeral.yml` / "Image Build Pipeline (Ephemeral)" workflow) implements 1:1 provisioning: it counts the
> targets in inventory (respecting `--limit`) and launches that many builders.

## Role input validation

Each project role declares its input contract in `meta/argument_specs.yml`. Ansible validates it automatically at
role entry, including roles invoked through `include_role` and the Windows builder-side Ansible process. No CLI
flag is needed. Defaults remain in each role's `defaults/main.yml`; specs do not introduce fallback values.

Missing inputs marked `required: true` produce argument-validation errors. Resolving templated inputs can also fail
with undefined-variable errors, such as when a default alias references a missing injected secret.

Inputs with no usable fallback are declared without assignments in role defaults and marked required in the spec.
An empty default is appropriate only when it has a supported meaning, such as skipping an optional operation or
omitting an explicit AWS credential override. Guards can still reject explicitly supplied empty required inputs.

Contracts include every declared default and caller-settable source setting, including derived paths and retained
configuration for future consumers. Derived settings remain optional at entry when the role normally computes them;
higher-precedence caller values are checked when present. Module return structures remain runtime results.

Organize each spec with secrets first, inherited and derived execution context next, then functional groups.
Use `##` comment headers with a blank line between groups, omitting empty sections. Keep related required and
optional settings together. Tool-specific computed paths, URLs, and aliases stay with their functional groups;
the inherited and derived section covers builder selection, build identity, upstream results, and runtime facts.
Descriptions explain purpose or behavior rather than repeating variable names.

Within each section, list `required: true` inputs before other inputs while keeping the relative order in each group.
Order option fields as `type`, `description`, `required`, and `no_log`, omitting fields that do not apply; put remaining
attributes such as `choices`, `elements`, and nested `options` afterward. Apply the same field order to nested options.

Specs cover required inputs, types, list elements, nested structures, and supported fixed choices. They accept
some convertible values without normalizing role variables. Tasks retain strict handoff checks, semantic bounds,
cloud-conditional requirements, and checks against files, builders, and build results. AWS credential overrides
remain optional so environment and instance-role authentication continue to work.

Task-level guards supplement specs with semantic and strict native-type checks before state-changing work. Keep
provider-specific prerequisites inside the selected cloud branch. Check existing artifacts after their paths are
resolved and before editing or publication; checks of newly generated content remain after its producing step.

## Supported Image Variants

- **RHEL** (Image Builder / osbuild-composer)
  - Versions: 8.10, 9.2, 9.4, 9.6, 9.8
  - Profiles: base, appserver, database
  - Output: qcow2 -> AMI (VHD + GCP planned via `cloud_convert`)
  - Matrix: **{versions} x {profiles} x {clouds}** = 45 phantom hosts (15 AWS-only)

- **Windows Server** (Packer)
  - Versions: 2022, 2025
  - Profiles: base, jumphost
  - Output: AMI (Azure/GCP planned; each cloud target needs its own Packer builder and source image)
  - Matrix: **{versions} x {profiles} x {clouds}** = 12 phantom hosts (4 AWS-only)

- **Ubuntu** (Packer)
  - Versions: 22.04, 24.04, 26.04
  - Profiles: base, k8s-node
  - Output: planned
  - Matrix: **{versions} x {profiles} x {clouds}** = 18 phantom hosts (6 AWS-only)

**v1 totals:** 75 phantom hosts across all clouds. AWS-only (the only fully implemented cloud): 25 builds.

## Architecture

### Build Methods

- **Image Builder (RHEL):** RHEL Image Builder (osbuild-composer) on an EC2 builder instance. A TOML blueprint defines
  packages, FIPS, STIG profile, partition layout, and cloud-init configuration. The compose produces a hardened qcow2
  directly; no ISOs, no KVM, no booting a guest VM.
- **Packer (Windows):** Packer with an Ansible provisioner handling STIG hardening and profile customization. Currently
  uses the amazon-ebs builder for AWS AMIs. Future: azure-arm and googlecompute builders for Azure/GCP.

### RHEL Build Pipeline

```
1. Blueprint TOML -> osbuild-composer -> qcow2
2. FIPS verify + STIG scan (oscap-chroot, offline)
3. image_prepare: compress canonical qcow2 and record SHA-256
4. cloud_convert: convert, upload, and register the target cloud's native image
5. cloud_validate: boot target-cloud guest -> authenticate over SSH -> clean up guest resources
6. image_validation_gate: check this attempt's native-image validation and cleanup evidence
7. rhel_artifacts_prepare: verify qcow2 checksum, generate metadata, select files
8. artifactory_upload: upload the explicit producer artifact list
9. artifactory_release_bundle: create/sign the JFrog Release Bundle
10. image_release_approve: approve the native image and emit its distribution record
```

This is **golden qcow2** workflow; one compose per variant, producing a single qcow2 that is the source of truth.
Cloud-specific formats are derived from it. See [Output Format Options](#output-format-options) for the rationale and
how to switch to per-cloud composes if needed.

Every target cloud has the same mandatory publication gate: successful native image registration, authenticated SSH,
and temporary-resource cleanup. Failed native images remain for debugging; their qcow2 and reports are not uploaded.
All target-cloud dispatch lives inside roles. The builder infrastructure always remains in AWS.

AWS conversion uses qcow2 -> raw -> S3 -> AMI. Set `rhel_smoke_subnet_id` and `rhel_smoke_security_group_ids` for its
validation guest. Azure currently converts to VHD and GCP creates a disk archive, but their native registration,
guest validation, publication approval, and distribution handlers remain TODOs. They fail explicitly until implemented.
The shared workflow is ready for those handlers; Azure/GCP are not yet operational end to end.

See [cloud_validate](roles/cloud_validate/README.md) for the provider-neutral image and validation record contract,
and [rhel_ami_validate](roles/rhel_ami_validate/README.md) for the implemented AWS guest test. Future Azure/GCP work
fills in provider task files and inventory settings without adding target-cloud branches to `build_rhel.yml`.

Every producer follows the same explicit release stages: `image_build_initialize`, OS/method-specific build and guest
validation, `image_validation_gate`, producer artifact preparation, `artifactory_upload`, `artifactory_release_bundle`,
and `image_release_approve`. No upload role creates a bundle or grants approval internally. Each producer generates
its own metadata and file list; the uploader is shared across artifact types. See the
[release approval contract](roles/image_release_approve/README.md). Approval is recorded only after uploads, bundle
creation, and provider approval succeed. It emits `published_image` locally and a
unique `image_publication_<target SHA-256>` AAP artifact per target, so converging producer jobs cannot overwrite a
shared mapping. Distribution requires that record for every target and dispatches solely by cloud provider.
OS and build method are provenance; raw AMI IDs cannot bypass approval.
OS-specific build playbooks select their own family and supported method together, so a future OS sharing Packer or
osbuild is not accidentally sent through the existing Windows or RHEL producer.

For an existing local qcow2, use `--tags prepare,convert,smoke,export` and supply its assigned `_builder_host`.
An `--tags export` invocation alone fails because it has no successful evidence from the current attempt.

### Windows Build Pipeline and Ansible Execution Boundary

**The outer AAP/CLI playbook does not call `windows_hardening` directly.** It calls `windows_image_build`, which
renders Packer files and runs Packer on a Linux builder. Packer then launches a separate Ansible process on that
builder to apply hardening to the temporary Windows guest over WinRM. The Windows guest does not run Ansible itself.

```text
AAP/CLI: build_windows.yml -> windows_image_build
  -> Linux builder: packer build -> provisioner "ansible" -> ansible-playbook <vm_name>-harden.yml
     -> windows_hardening -> win2022stig -> Windows guest modules over WinRM
```

Hardening, the pre-seal scan, report download, and Sysprep occur within the Packer build, before AMI capture.
Post-AMI validation is a later outer pipeline step using `windows_ami_validate`.

The builder-side Ansible environment and variables are separate from the outer run. Each build now prepares an
isolated environment, stages project roles and pinned dependencies, and passes selected settings in YAML files.
Use `windows_stig_overrides` for provider rule toggles. See the
[windows_hardening execution contract](roles/windows_hardening/README.md#who-calls-this-role-and-where-it-runs)
for the exact call sites, builder prerequisites, and variable pass-through limits.

### Inventory Model

Build targets are modeled as phantom hosts in five group dimensions (OS family, OS version, profile, build method,
cloud provider). Each phantom host merges `group_vars` from all five dimensions. For the full model, variable
placement rules, and how-to recipes for adding new OS versions, profiles, or OS families, see
[inventory/README.md](inventory/README.md).

### Builder Instances

Builder instances are EC2 instances discovered by EC2 tags, one or more per build method. In the ephemeral model, fresh
instances are provisioned from pre-baked AMIs at pipeline start and terminated at the end. In the v1 (static) model,
persistent instances are stopped between runs and started by the workflow.

### Hardening

- **FIPS (RHEL):** Enabled at build time via `[customizations.fips]` in the blueprint. Verified post-compose by
  offline inspection of crypto-policies and kernel cmdline in the built image.
- **FIPS (Windows):** The Ansible Lockdown STIG role sets the `FIPSAlgorithmPolicy\Enabled` registry key. The
  `windows_ami_validate` role verifies the flag on a fresh instance booted from the registered AMI. See the Release
  Artifacts section for caveats on what this check does and does not confirm.
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
qcow2`. The qcow2 is the golden artifact pushed to Artifactory. For AWS, `cloud_convert` derives a raw staging disk,
imports it as an AMI, and `cloud_validate` dispatches its SSH test before publication. Azure and GCP use the same
ordering, with unimplemented provider operations explicitly blocked.

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
3. Update producer artifact lists to select the new formats; the uploader stays unchanged
4. Replace `cloud_convert` with `cloud_upload` (upload + register only)
5. Update `build-metadata.json.j2` to record the compose per format

## Usage

### Running from CLI

Use `ansible-navigator` to run playbooks inside the project's Execution Environment (same container AAP uses). The
`ansible-navigator.yml` config in this directory sets the EE image and defaults to `stdout` mode, so output goes
straight to your terminal like `ansible-playbook` would.

```bash
# Full pipeline, all targets (start builders through stop builders)
ansible-navigator run playbooks/site.yml

# Build only RHEL 9 variants (build step only; no lifecycle)
ansible-navigator run playbooks/build_rhel.yml -- --limit 'rhel_9_*'

# Build a single image
ansible-navigator run playbooks/build_rhel.yml -- --limit rhel-9.4-base-aws

# Build all database profiles across RHEL
ansible-navigator run playbooks/build_rhel.yml -- --limit profile_database

# Build RHEL 9 x base x AWS only (intersection)
ansible-navigator run playbooks/build_rhel.yml -- --limit 'rhel_9_*:&profile_base:&cloud_aws'
```

> **Interactive mode:** For long or complex runs, try `--mode interactive` to get the TUI. It lets you drill into
> individual tasks, inspect per-host results, and browse play-by-play output after completion. Especially useful when
> debugging a single failing target in a multi-image run: you can expand the failed host's task output without
> scrolling through dozens of successful hosts.

> **Note:** `--limit` on `site.yml` applies to ALL plays, including lifecycle plays that target `localhost` or the
> `builders` group. A limit like `profile_database` would skip `start_builders`, `configure_builders`, etc. For scoped
> full-pipeline runs, use the AAP Workflow Template with a Limit instead. For CLI, use `site.yml` without a limit for
> the full pipeline, or run individual build playbooks with `--limit` as shown above.

> **Windows builds:** The default EE (`ee-base`) does not include `pywinrm` or `ansible.windows`. For Windows builds,
> override the EE image: `ansible-navigator run playbooks/build_windows.yml --eei
> artifactory.example.com/docker-local/ee-images/ee-windows:latest -- --limit profile_jumphost`

### Running from AAP

- **Workflow Template (normal operation):** Launch "Image Build Pipeline" for a full run (start builders -> configure
  -> build RHEL + Windows in parallel -> distribute -> stop builders). The workflow has `ask_limit_on_launch`, so you
  can scope builds to specific targets (e.g., `profile_database`, `rhel_9_*`, `rhel-9.4-base-aws`). The limit only
  flows to the build JTs (which accept prompted limits); lifecycle steps (start/stop builders, configure, distribute)
  always run unscoped. Individual image failures are caught and reported at the end; one bad image doesn't prevent the
  rest from building. The ephemeral variant ("Image Build Pipeline (Ephemeral)") has the same structure but provisions
  and tears down builders instead of starting and stopping them.
- **Individual Job Templates (ad-hoc):** The build templates ("Build RHEL Images", "Build Windows Images") have
  `ask_limit_on_launch: true`, so you can run them standalone with a Limit for one-off rebuilds. This skips the
  lifecycle steps; make sure builders are already running.

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

The lint configuration excludes the provider preflight playbook because standalone linting lacks its
`windows_stig_role` input. The build syntax-checks it with the actual `hardening.yml` payload before starting Packer.

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
├── .pinned_versions.yml           # pinned dependency versions + SHA-256 checksums
├── .refresh_checksums.py          # script to fetch/verify checksums from upstream
├── requirements.yml               # collection dependencies
├── roles/
│   ├── builder_configure/         # configure builder (osbuild-composer, Packer)
│   ├── builder_ansible_prepare/   # isolated runtime, staged roles, and typed settings for guest provisioning
│   ├── rhel_image_build/          # blueprint compose via composer-cli
│   ├── rhel8_fstab_fixup/         # post-compose fstab fixup for RHEL 8 on RHEL 9 builders
│   ├── rhel_compliance_scan/            # offline FIPS verify + STIG scan
│   ├── image_prepare/             # compress canonical qcow2 and record checksum
│   ├── cloud_validate/           # dispatch target-cloud boot, SSH, and cleanup validation
│   ├── rhel_ami_validate/         # implemented AWS guest validation behind cloud_validate
│   ├── rhel_artifacts_prepare/    # verify qcow2 checksum, generate metadata, select files
│   ├── windows_artifacts_prepare/ # generate metadata and select Windows compliance evidence
│   ├── artifactory_upload/        # upload explicit producer-selected files
│   ├── cloud_convert/             # qcow2 -> AMI/VHD/GCP image conversion
│   ├── windows_image_build/       # Packer build with Ansible provisioner (currently amazon-ebs)
│   ├── windows_hardening/         # Packer-launched Ansible on builder; hardens Windows guest over WinRM
│   ├── windows_compliance_scan/   # Packer-launched Ansible on builder; pre-seal guest scan over WinRM
│   ├── windows_ami_validate/      # Post-AMI PowerSTIG scan (boots AMI; authoritative compliance evidence)
│   ├── artifactory_release_bundle/ # JFrog Release Bundle v2 create/sign (shared)
│   ├── image_build_initialize/    # unique attempt identity and cleared state
│   ├── image_validation_gate/     # native-image validation/cleanup checks
│   ├── image_release_approve/     # native approval and distribution record
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

Pinned versions live in the files below; check these for current requirements rather than duplicating versions here.

- **Ansible collections and roles:** [`requirements.yml`](requirements.yml) (installed by AAP at project sync)
- **Python packages and system packages:** the `ee-images` repository (`base/` and `windows/` EE definitions)
- **`pywinrm`:** needed on the builder host for Packer's Ansible provisioner (the EE copy does not help the Packer
  path); installed by `builder_configure`
- **`qemu-img`:** system package on the osbuild builder for image format conversion; installed by `builder_configure`

## Supply Chain Verification

Every external binary, library, and collection fetched during the build pipeline is version-pinned. Where possible,
SHA-256 checksums are verified at download time. The single source of truth for all pinned versions and checksums is
[`.pinned_versions.yml`](.pinned_versions.yml); the companion script
[`.refresh_checksums.py`](.refresh_checksums.py) fetches checksums from upstream APIs.

### What is verified

| Artifact            | Version Pin         | Integrity Check                                         |
|---------------------|---------------------|---------------------------------------------------------|
| Packer binary       | Exact (`1.16.1`)    | SHA-256 verified by `get_url` on download. Hash sourced |
|                     |                     | from GPG-signed `SHA256SUMS` published by HashiCorp.    |
| Packer plugins      | Exact (`= X.Y.Z`)   | `packer init` verifies plugins via GPG signature over   |
|                     |                     | SHA-256 checksums (HashiCorp registry). See below.      |
| pip packages        | Exact (`==0.5.0`)   | Version pinned; PyPI SHA-256 recorded in                |
|                     |                     | `.pinned_versions.yml` for audit.                       |
| Ansible collections | Exact (`12.0.0`)    | Version pinned; Galaxy SHA-256 recorded in              |
|                     |                     | `.pinned_versions.yml` for audit.                       |
| PowerSTIG           | Exact (`4.30.0`)    | Version pinned; post-install manifest hash check        |
|                     |                     | (once `powerstig_manifest_hash` is populated).          |
| NuGet provider      | Exact (`2.8.5.201`) | Version pinned.                                         |
| Yum repos           | Repo-level          | `gpgcheck: 1` on all repo definitions; RPM GPG          |
|                     |                     | signatures verified by dnf.                             |
| Windows-2022-STIG   | Git tag (`2.9.0`)   | Pinned tag in `requirements.yml`.                       |

### Why Packer plugin checksums do not need manual verification

`packer init` downloads plugins from the HashiCorp registry, which serves each release with a `SHA256SUMS` file and
a detached GPG signature (`SHA256SUMS.sig`). Packer verifies the GPG signature against HashiCorp's embedded public
key, then verifies the downloaded plugin zip's SHA-256 against the signed sums file. This is the same two-layer
verification chain (GPG signature over SHA-256 checksums) that Terraform uses for providers. It is strictly stronger
than the SHA-256-only check applied to the Packer binary itself. Pinning plugins to exact versions (instead of
`~> 1`) prevents a future release from being pulled in silently.

### Ansible collections: current limitations and future mitigation

Ansible Galaxy does not support checksum or signature verification for collection tarballs. The Galaxy API
*exposes* a SHA-256 per tarball, but `ansible-galaxy` does not verify it during installation. Exact version pins
prevent silent upgrades but do not verify integrity of the downloaded artifact.

**Future mitigation:** collections will be pre-vetted and stored in Artifactory, so builders pull from an internal
trusted source rather than public Galaxy. This adds a trust boundary (Artifactory artifact integrity) and enables
offline/air-gapped operation.

### How to update pinned versions

1. Edit the `version:` field in [`.pinned_versions.yml`](.pinned_versions.yml).
2. Run `python .refresh_checksums.py` to fetch the new checksum from upstream.
3. Update the corresponding Ansible inventory files to match:
   - [`inventory/group_vars/builders_packer.yml`](inventory/group_vars/builders_packer.yml): Packer version/checksum,
     pip packages, plugin versions, builder-side collections
   - [`inventory/group_vars/windows_targets.yml`](inventory/group_vars/windows_targets.yml): PowerSTIG, NuGet
   - [`requirements.yml`](requirements.yml): Ansible collections
4. Commit both `.pinned_versions.yml` and the updated inventory files.

For **PowerSTIG** and **NuGet** (Windows-only): hashes must be gathered from a Windows environment. See the
instructions in [`roles/windows_compliance_scan/defaults/main.yml`](roles/windows_compliance_scan/defaults/main.yml).

## Future: Adding Ubuntu Support

See [Adding a New OS Family](inventory/README.md#adding-a-new-os-family-eg-a-hypothetical-new-platform)
for the structural checklist.
Ubuntu-specific implementation notes:

- **Build method:** `autoinstall` (cloud-init-based, not kickstart/anaconda). Could use Ubuntu's Image Builder
  equivalent or a virt-install autoinstall approach.
- **Install template:** `ubuntu2404-blueprint.toml.j2` (if using Image Builder) or `ubuntu2404.autoinstall.j2` in an
  `ubuntu_iso_build` role.
- **Hardening:** STIG/CIS remediation tooling TBD (oscap with Ubuntu SCAP content or Canonical's USG).
- **Reused roles:** `builder_configure`, `image_build_initialize`, `image_validation_gate`, `artifactory_upload`,
  `artifactory_release_bundle`, `image_release_approve`, and `image_distribute` provide shared pipeline stages.
  Reuse `cloud_convert` when the producer starts from qcow2; Packer native images skip conversion.
