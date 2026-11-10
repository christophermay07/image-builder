# Goals

## What This Project Is and Why It Exists

author needs a **secure image build factory,** which is a single, repeatable pipeline that produces hardened VM images
and delivers them to clients.

Clients run in **multiple clouds** (AWS, Azure, GCP today; others possible in the future) and on **multiple operating
systems** (RHEL, Windows Server, Ubuntu). Every image must pass **DISA STIG audit** and ship with a compliance report
proving it. The pipeline is the authoritative source for every golden image the organization delivers.

The goal is **one process** that:

1. Builds a hardened base image for each supported OS version.
2. Layers product-specific configurations on top of the base to produce **profiled images** (e.g., a database workload image that
   includes the packages and settings database workload requires).
3. Converts each image to the cloud-native format for every target cloud.
4. Pushes the image, compliance artifacts, and metadata to Artifactory as a release bundle.
5. Distributes the image to the appropriate cloud accounts.

The pipeline replaces ad-hoc, per-client image preparation with a standardized, auditable, and extensible factory.

## Assumptions

**Internet egress.** The pipeline assumes builder EC2 instances and Packer guest VMs have **outbound internet access**
(via NAT gateway or equivalent). This is not a disconnected or air-gapped build environment. Multiple pipeline
components depend on runtime access to external package sources:

- **RHEL:** osbuild-composer pulls packages from Red Hat CDN (or a Satellite / Artifactory RPM mirror).
- **Windows:** PowerSTIG is installed from the PowerShell Gallery during the Packer build. The MindPoint Group
  collection is installed from the Ansible content source (Automation Hub, Galaxy, or Artifactory).
- **Packer:** `packer init` downloads plugins from the HashiCorp registry at build time.
- **Ansible collections:** Installed from Galaxy or Automation Hub at AAP project sync time.

If egress is ever restricted, each of these dependencies has an offline staging path (Artifactory mirrors, pre-baked
EEs, `packer plugins install --path`, local PowerShell module repositories), but those paths are not implemented today
and would require additional work. A move to disconnected builds would be a significant architectural change, not a
configuration toggle.

## The Profile Model

The build matrix is **{OS versions} × {profiles}**. Every OS version gets a **base** profile (the hardened,
STIG-compliant foundation). On top of base, product profiles add packages, configurations, and tailoring rules specific
to that product.

Today:

- **base:** hardened OS with FIPS enabled, STIG applied, cloud-init configured.
- **appserver:** base + application server packages, configuration, and any STIG rule tailoring required by the application
  NetWeaver / ERP application application servers.
- **database:** base + database workload-specific packages, filesystem layout adjustments (e.g., /data/db, /data/log), and
  tuning.
- **jumphost:** base + bastion/jumphost configuration for Windows.
- **k8s-node:** base + Kubernetes node configuration for Ubuntu.

In the future, additional profiles may appear for other application products or entirely different workloads.

### Profile composition rules

Every profile is **base + that profile's additions**. Composition is strictly additive:

- A profile can add packages, add configuration, add filesystem customizations, and add entries to the list of
  unselected STIG rules.
- A profile **cannot remove or override** anything the base profile provides. Even items that look subtractive (like
  unselecting a STIG rule that base selects) are implemented as additions to the unselected-rules list, not as deletions
  from the selected-rules list.

### What is out of scope

**Aggregated profiles.** The pipeline does not support combining two non-base profiles into a single image. Each image
is exactly "base + one profile." There is no mechanism for producing "base + database workload + SomeOtherProduct" without creating
a new, dedicated profile that carries the combined configuration of both. If that need arises, the answer is a new
profile, not a composition engine.

## Toolchain

### Ansible (on AAP 2.7)

The entire pipeline is Ansible, running on Ansible Automation Platform 2.7. AAP provides the execution environment (a
container with Ansible, boto3, collections, and connection plugins), credential injection from HashiCorp Vault, workflow
orchestration (fork/join for parallel RHEL and Windows builds), and RBAC for operators.

### RHEL image builds: osbuild-composer (Image Builder)

RHEL images are built using Red Hat's Image Builder (`osbuild-composer`) on a dedicated EC2 builder instance. A TOML
blueprint defines packages, FIPS mode, STIG profile, partition layout, and cloud-init configuration. The compose
produces a hardened qcow2 directly (no ISOs, no KVM, no booting a guest VM.)

FIPS is enabled at compose time (`[customizations.fips]`). STIG is applied during the compose via
`[customizations.openscap]` with blueprint-level tailoring for rule overrides. Post-compose, offline verification (FIPS
check + `oscap-chroot` scan) confirms compliance without ever booting the image.

### Windows image builds: Packer

Windows images are built using HashiCorp Packer with an Ansible provisioner. Packer launches a temporary EC2 instance
from a base Windows Server AMI, connects via WinRM, runs STIG hardening (MindPoint Group collection) and a pre-seal
compliance scan (PowerSTIG), then generalizes and snapshots the result into an AMI. After the AMI is registered, a
post-AMI validation step boots a fresh instance from the AMI and runs PowerSTIG again to produce the authoritative
compliance evidence for the shipped artifact.

### Cloud format conversion: qemu-img

RHEL images are built as qcow2 (the "golden artifact"), then converted to cloud-native formats using `qemu-img`:

- **AWS:** qcow2 → raw → S3 upload → `import-snapshot` → register as AMI (UEFI boot).
- **Azure:** qcow2 → VHD (note: the `qemu-img` format flag is `vpc`, not `vhd`).
- **GCP:** qcow2 → raw → tar.gz → `gcloud compute images create`.

Windows images skip conversion; Packer produces cloud-native images directly.

### Artifactory

Every successful build produces a release bundle pushed to JFrog Artifactory:

- The image artifact (qcow2 for RHEL, AMI ID reference for Windows).
- OpenSCAP or PowerSTIG compliance report (HTML + XML/JSON).
- Build metadata (timestamp, compose UUID, STIG profile, builder ID).

Release Bundles (JFrog Lifecycle API v2) group all artifacts for a build into a distributable, optionally signed unit.

### Compliance tooling

| OS      | Hardening                                           | Audit                                                |
|---------|-----------------------------------------------------|------------------------------------------------------|
| RHEL    | OpenSCAP via blueprint `[customizations.openscap]`  | `oscap-chroot` offline scan against DISA STIG        |
|         |                                                     | datastream (single scan; target IS the artifact)     |
| Windows | MindPoint Group STIG collection (per-rule boolean   | PowerSTIG: pre-seal scan (build diagnostic) +        |
|         | toggles)                                            | post-AMI scan (compliance evidence for the shipped   |
|         |                                                     | artifact)                                            |

RHEL produces one compliance report per build. Windows produces two: a pre-seal scan inside the Packer guest
(catches hardening failures early) and a post-AMI scan against a fresh instance booted from the registered AMI
(validates the actual shipped artifact). Both are included in the release bundle. The offline approach for RHEL
(guestmount + `oscap-chroot`) means the image never needs to boot for validation; the qcow2 is scanned directly on
the builder. Windows needs a post-AMI scan because Sysprep, deferred STIG rule re-application, and first-boot
re-initialization all modify system state after the pre-seal scan. See
[WINDOWS-APPROACH.md](WINDOWS-APPROACH.md#why-two-scans-for-windows-but-one-for-rhel) for the full rationale.

## How Image Builds Run

All image building happens in **AWS**. Builder EC2 instances live in a build account and are managed with a stop/start
lifecycle: stopped between pipeline runs, started automatically at the beginning of each run by the AAP workflow.

The following builder types handle the full matrix:

| Builder                | What it builds                      | Tools                                                 |
|------------------------|-------------------------------------|-------------------------------------------------------|
| RHEL builder (osbuild) | All RHEL versions × all profiles    | osbuild-composer, qemu-img, openscap-scanner,         |
|                        |                                     | libguestfs-tools                                      |
| Packer builder         | All Windows versions × all profiles | Packer                                                |

After building, images are converted (if needed) to the target cloud format, then distributed:

```
Build (AWS)
  → Harden + scan (on builder, in AWS)
  → Export to Artifactory (qcow2 + reports + metadata)
  → Convert to cloud-native format (AMI, VHD, GCP image)
  → Distribute to target accounts / regions
```

The operational documentation covers a detailed breakdown of every machine involved and what runs where.

## How Image Handoff Works

The pipeline ends at **delivery**. Deployment from the delivered image is owned by the receiving team.

### The delivery pattern

Finished images are delivered using a **copy** pattern for cross-account distribution: the build account shares the
image with the target account, and the target account copies it into a locally-owned image. This decouples lifecycles:
the build account can clean up old images without breaking the target account's references.

### How consumers find the latest image

The recommended approach is **SSM Parameter Store**: the pipeline writes the latest AMI ID to a well-known path (e.g.,
`/golden-images/rhel-9.4/base/latest`), and consumers reference the parameter in their Terraform, CloudFormation, or
Launch Templates. This provides an atomic, programmatic pointer without requiring consumers to understand the tagging
schema.

Tags are applied regardless for AWS Console visibility and manual inspection. See
[AWS-IMAGE-DELIVERY.md](aws/AWS-IMAGE-DELIVERY.md) for the full delivery contract, KMS considerations, and alternative
handoff options.

### Retention

A cleanup role handles AMI deregistration and EBS snapshot deletion in the build account. Because target accounts own
independent copies, build-side cleanup does not affect them. Each side manages its own retention independently.

## How the Team Operates

### Adding to the build matrix

The inventory uses a five-dimensional phantom-host model (OS family, OS version, profile, build method, cloud
provider). Adding a new image variant means:

- **New OS version:** Add a phantom host entry and a `group_vars` file with the version-specific variables.
- **New profile:** Add a profile group, its `group_vars` file with profile-specific packages and tailoring, and a
  phantom host per OS version.
- **New OS family (e.g., Ubuntu):** Add the OS-family group, build method, roles for that family's build toolchain, and
  phantom hosts.

Recipes are in [inventory/README.md](../inventory/README.md#quick-reference).

### Pipeline operation

The full pipeline is `playbooks/site.yml`, which chains:

```
start builders → configure → build RHEL (parallel with) build Windows → distribute → stop builders
```

Operators can build the full matrix or any slice of it using `--limit`:

```bash
# Everything
ansible-playbook playbooks/site.yml

# Just RHEL 9.8 base
ansible-playbook playbooks/site.yml --limit 'rhel_9_8:&profile_base'

# All Windows
ansible-playbook playbooks/site.yml --limit windows_targets
```

In AAP, the same filtering is done via the **Limit** field on job templates or workflow launches.

### Failure handling

Individual image failures are caught and recorded; one bad image does not prevent the rest of the matrix from building.
The pipeline reports all failures at the end, after every target has had its chance.

### Infrastructure prerequisites

The pipeline builds images but does not provision its own infrastructure. Builder EC2 instances, network connectivity,
Vault paths, Artifactory repositories, AAP configuration, and RHEL entitlements must all exist before the first run. The
full list is tracked in [OPEN-REQUIREMENTS.md](OPEN-REQUIREMENTS.md).
