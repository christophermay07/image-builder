# Credentials

> **On permissions listed in this document:** High-level permissions describe what the pipeline needs to do (e.g., "create
> and manage EC2 instances," "upload artifacts to Artifactory"). These are what we expect the pipeline to require and are
> unlikely to change. Low-level permissions (specific IAM actions, API scopes) are provided as a reference derived from
> the roles and modules the pipeline uses today. They may not be exact; a permission might be missing, or one might be
> listed that turns out not to be needed. Treat the high-level descriptions as the contract; treat the low-level lists
> as a starting point, not a specification.

## Primary: HashiCorp Vault

All secrets are sourced from HashiCorp Vault (single root namespace). AAP uses the built-in "HashiCorp Vault Secret
Lookup" credential type to pull secrets at job launch time; secrets never persist in AAP's database.

Credentials used by this pipeline:

| Credential        | Vault Path (TBD)                           | AAP Credential Type | Used By                       |
|-------------------|--------------------------------------------|---------------------|-------------------------------|
| aws_credential    | dynamic; see                               | Amazon Web Services | AWS job templates             |
|                   | [AWS Credentials](#aws-credentials)        |                     |                               |
| builder_ssh_key   | `secret/data/image-builder/ssh`            | Machine             | configure_builders, build_*   |
| artifactory_token | `secret/data/image-builder/artif`          | Custom              | build_* (release bundle push) |
| windows_winrm     | `secret/data/image-builder/winrm`          | Machine (Windows)   | build_windows                 |

<!-- TODO: confirm Vault paths with Vault admin -->
<!-- TODO: confirm Vault KV engine version (v1 vs v2); path format differs -->
<!-- Artifactory custom credential type: see open question #5 and ADR-IF-027 -->

## Job Runtime Credentials

Beyond the AAP credential objects above, the pipeline uses additional credentials at runtime. These are resolved from
Vault at job launch and injected as environment variables or files for the life of the job. Nothing persists after the
job completes.

### Artifactory Identities

| Credential                         | Purpose                     | Permission                  | Notes                        |
|------------------------------------|-----------------------------|-----------------------------|------------------------------|
| `artifactory_token_image_upload`   | Upload built images (qcow2) | Deploy only, no delete, no  | Used by `image_export` role  |
|                                    | to Artifactory              | overwrite                   |                              |
| `artifactory_token_scan_upload`    | Upload compliance scan      | Deploy only                 | Used by                      |
|                                    | results and build metadata  |                             | `image_release_publish` role |
| `artifactory_token_release_bundle` | Create and sign Release     | Manage release bundles      | Used by                      |
|                                    | Bundle v2                   |                             | `artifactory_release_bundle` |
|                                    |                             |                             | role                         |

The image-upload and scan-upload identities are deliberately separate: they have different retention policies and
different downstream consumers. Keeping them distinct means a compromised scan-upload token cannot overwrite a
production image.

### Signing

| Credential  | Purpose                               | Permission | Notes                                              |
|-------------|---------------------------------------|------------|----------------------------------------------------|
| Signing key | Sign image manifests and scan results | Sign only  | Vault Transit; private key never materializes. See |
|             |                                       |            | [Image Signing](#image-signing-decision-required)  |

### AWS

| Credential        | Purpose             | Permission                                  | Notes                          |
|-------------------|---------------------|---------------------------------------------|--------------------------------|
| AWS build session | EC2 lifecycle,      | See                                         | One-hour STS credentials from  |
|                   | image creation, KMS | [IAM Role Separation](#iam-role-separation) | Vault AWS secrets engine       |

### POC Identity Strategy

The pipeline is **architected** for separation of duties across AWS functions and Artifactory scopes; each role uses its
own credential variable (`aws_build_*`, `aws_distribute_*`, `aws_cleanup_*` for AWS; `artifactory_token_image_upload`,
`_scan_upload`, `_release_bundle` for Artifactory). See `inventory/group_vars/all.yml` for the variable definitions.

**For the POC, all function-specific variables point to a single shared identity per provider.** This avoids losing
time to permission-provisioning delays while the pipeline is being stood up. To split later:

1. Create the additional credentials in Vault (or request them from the platform team).
2. Override only the function-specific variables in inventory or AAP extra-vars.
3. No role or playbook code changes are needed; the separation points are already in the code.

This approach means the security posture improves incrementally: start with a working pipeline on one identity, then
tighten without rework.

## AWS Credentials

AWS credentials are **not** stored as static access keys. The pipeline uses Vault's AWS secrets engine to generate
short-lived STS credentials on demand. Each AAP job run receives fresh, time-limited credentials that expire after the
job completes.

This means:

- No persistent IAM access key exists in AAP, Vault KV, or anywhere else.
- No key rotation is required; credentials are ephemeral by design.
- Vault manages the underlying IAM configuration; the pipeline team does not handle AWS credential lifecycle.

The Vault AWS secrets engine was configured by the Vault administration team. The connection path is established and
operational.

## AWS Permissions

The pipeline needs to do the following with AWS. The two build methods (osbuild for RHEL, Packer for Windows) have
different image-creation paths, so the permission set is a union of both.

| What                                                 | Why                                        | Which build method               |
|------------------------------------------------------|--------------------------------------------|----------------------------------|
| Create, start, stop, and terminate EC2 instances     | Build hosts for Packer and                 | Both                             |
|                                                      | osbuild-composer                           |                                  |
| Create AMIs from running instances (`CreateImage`)   | Capture the finished Windows image         | Windows (Packer `amazon-ebs`)    |
| Upload qcow2 to S3 and import as AMI (`ImportImage`) | Convert the osbuild qcow2 into an AMI      | RHEL (osbuild → `cloud_convert`) |
| Tag EC2 resources                                    | Track images by OS, profile, build         | Both                             |
|                                                      | timestamp                                  |                                  |
| Manage temporary key pairs or SSM sessions           | Connect to builder instances during        | Both                             |
|                                                      | provisioning                               |                                  |
| Create and manage security groups                    | Packer manages its own SG for WinRM access | Windows                          |
| Encrypt and decrypt with KMS                         | AMI and snapshot encryption                | Both                             |
| Upload objects to S3                                 | Stage the qcow2 for VM Import              | RHEL                             |
| Pass IAM roles to EC2 instances and                  | Builder instance profile; AWS VM           | Both (one PassRole target for    |
| to the `vmimport` service                            | Import service role                        | Windows, two for RHEL)           |
| Copy AMIs across regions                             | Multi-region availability                  | Both (post-build)                |
| Share AMIs with other accounts                       | Cross-account delivery to the target       | Both (post-build)                |
|                                                      | account                                    |                                  |
| Deregister AMIs and delete snapshots                 | Lifecycle cleanup of old images            | Both (cleanup)                   |

### IAM Role Separation (Recommended)

When the pipeline moves beyond POC, these permissions should be split into three roles with distinct risk profiles:

| Role             | Purpose                               | Risk Profile                            |
|------------------|---------------------------------------|-----------------------------------------|
| **Builder**      | EC2 lifecycle, image creation, KMS    | Moderate; creates and manages resources |
| **Distribution** | Cross-account AMI copy and sharing    | Low frequency, crosses account boundary |
| **Cleanup**      | AMI deregistration, snapshot deletion | Destructive; separate approval path     |

**Why split?** The cleanup role can delete production images. The distribution role crosses account boundaries. Neither
capability should be available to routine build operations. Separating them means a compromised build session cannot
delete existing AMIs or modify cross-account sharing.

The pipeline code already uses separate credential variables per function (`aws_build_*`, `aws_distribute_*`,
`aws_cleanup_*` in `inventory/group_vars/all.yml`). Splitting is a configuration change, not a code change. See
[POC Identity Strategy](#poc-identity-strategy) for details.

See [AWS-IMAGE-DELIVERY.md](AWS-IMAGE-DELIVERY.md) for how the distribution role is used and the cross-account
mechanics.

### Detailed Permission Reference

> These are derived from the Ansible modules and Packer plugins the pipeline uses today. See the caveat at the top of
> this document; treat these as a starting point, not a specification.

**Builder function, common** (used by both build methods):

- `ec2:RunInstances`, `StopInstances`, `TerminateInstances`, `Describe*`
- `ec2:CreateKeyPair`, `DeleteKeyPair` (or SSM equivalents if using SSM connection)
- `ec2:CreateSnapshot`, `CreateTags`
- `iam:PassRole` scoped to the builder instance profile role
- `kms:Encrypt`, `Decrypt`, `GenerateDataKey`, `CreateGrant`, `ReEncryptFrom`, `ReEncryptTo` on the build CMK

**Builder function, Windows only** (used by `windows_image_build` / Packer `amazon-ebs`):

- `ec2:CreateImage` (snapshots a running instance into an AMI)
- `ec2:CreateSecurityGroup`, `DeleteSecurityGroup`, `AuthorizeSecurityGroupIngress`, `RevokeSecurityGroupIngress`
  (Packer creates a temporary SG for WinRM access)

**Builder function, RHEL only** (used by `cloud_convert` / VM Import):

- `s3:PutObject`, `s3:GetObject` on the VM Import staging bucket
- `ec2:ImportImage`, `ec2:DescribeImportImageTasks`
- `iam:PassRole` for the `vmimport` service role (a **second** PassRole target beyond the instance profile)
- The [`vmimport` service role](https://docs.aws.amazon.com/vm-import/latest/userguide/required-permissions.html)
  must exist in the account with access to the S3 bucket and EC2

**Distribution function** (used by `image_distribute`):

- `ec2:CopyImage`, `CreateTags`
- `ec2:ModifyImageAttribute` (launchPermission grant to target account)
- `ec2:ModifySnapshotAttribute` (createVolumePermission grant to target account)
- KMS key policy must grant the target account `kms:Decrypt`, `DescribeKey`, `CreateGrant`

**Cleanup function** (used by `ami_cleanup`):

- `ec2:DescribeImages`, `DescribeSnapshots`
- `ec2:DeregisterImage`, `DeleteSnapshot`

## Image Signing (Decision Required)

Image signing ensures that release artifacts (images, compliance reports) have not been tampered with between build and
deployment. Two approaches are viable; neither has been selected.

### Option A: Vault Transit

Vault's Transit secrets engine performs cryptographic operations server-side. The signing key never leaves Vault; the
pipeline sends a hash to Vault and receives a signature back.

**Advantages:**

- Private key material never appears in the execution environment or on any host.
- Key access is audited through Vault's audit log.
- Key rotation is a Vault operation; no pipeline changes needed.

**Disadvantages:**

- Requires Vault Transit to be configured and reachable from AAP (separate from the KV engine already in use).
- Consumers of the signature need access to the public key (or Vault's verify endpoint) to validate.
- Additional Vault infrastructure dependency.

### Option B: Artifactory GPG (Release Bundle Signing)

JFrog Release Bundle v2 supports GPG signing as a built-in feature. A GPG key pair is registered in Artifactory, and
release bundles are signed at creation time.

**Advantages:**

- Integrated with the Artifactory release bundle workflow already planned.
- Consumers verify signatures through Artifactory's API; no separate key distribution.
- Simpler operationally if Artifactory is already the artifact store.

**Disadvantages:**

- The GPG private key is stored in Artifactory. Anyone with Artifactory admin access can retrieve it.
- Key rotation requires Artifactory admin access and consumer coordination.
- Less auditability than Vault Transit for key usage.

### Current State

`release_bundle_signing_key` in `inventory/group_vars/all.yml` is an empty placeholder awaiting this decision. The
variable holds a GPG key alias for Option B. Option A would use a different mechanism (Vault path and Transit API call
in the `artifactory_release_bundle` role).

**Recommendation:** If Vault Transit is available, prefer it; the security argument (key never materializes) is
meaningful for a signing key that vouches for image integrity. If Transit is not available or adds unacceptable
complexity, Artifactory GPG is a reasonable fallback.

## Vault Setup in AAP

1. Create a "HashiCorp Vault Secret Lookup" credential with the Vault URL, auth method, and namespace.
2. For each pipeline credential, create the appropriate AAP credential type and link it to the Vault lookup credential
   via "External" input source.
3. Verify each credential resolves by running a test job.

## Fallback: Native AAP Credentials

> **When to use this:** If a specific credential cannot be sourced from Vault due to a platform limitation or bug (e.g.,
> multi-line SSH keys not retrieving correctly, custom credential type lookup failures, token renewal issues), store it
> natively in AAP as a temporary measure.

For any credential stored natively in AAP instead of Vault:

1. **Create the credential directly in AAP** using the same name and type as documented above. Store the secret value in
   AAP's encrypted database.
2. **Document the exception** in this section (below) with:
   - Which credential is affected
   - Why it can't be in Vault (the specific error/behavior)
   - The Vault path where it SHOULD live once the issue is resolved
3. **Tag the credential in AAP** with a description noting it's a Vault fallback (e.g., "VAULT-FALLBACK: see README for
   migration path").

**Migrating back to Vault** when the issue is resolved:

1. Store the secret in Vault at the documented path.
2. Create the Vault lookup credential (if not already present).
3. Edit the AAP credential: switch input source from "Manual" to "External" and select the Vault lookup credential.
4. Map the Vault secret fields to the credential fields.
5. Test by launching a job that uses this credential.
6. Remove the exception entry from this section.

**Current Vault fallback exceptions:**

_None yet. Document any here as they arise._

<!-- TODO: verify all credential types work with Vault in AAP 2.7 before
     go-live. If the alleged bug is confirmed, document it here. -->

## Bootstrap Exceptions

These are credentials that **structurally cannot** live in Vault because they exist before Vault is reachable or because
they bootstrap the trust chain that makes Vault accessible. Unlike the Vault fallback exceptions above (which are
temporary workarounds), these are permanent and accepted.

| Exception                              | Where It Lives                   | Why It Can't Be in Vault                                          |
|----------------------------------------|----------------------------------|-------------------------------------------------------------------|
| Vault admin / policy-writer credential | Held by platform automation      | Bootstraps the store that holds other secrets                     |
| Artifactory master / join key          | On disk at Artifactory install   | Predates any secret store; Artifactory is part of the trust chain |
| GitLab runner authentication token     | `config.toml` on the runner host | Set at runner registration, before any CI job can call Vault      |

These are **not** migration targets. They are inherent to the bootstrapping order of the infrastructure. Each is owned
by the platform or CI team, not the image build pipeline.

## Image Delivery Gate: Credential Leakage

Before delivering a golden image, verify these paths are clean. The build succeeds whether or not these contain
credentials; the failure mode is silent.

| Path                      | What leaks                                  | When it appears                      | Applies to |
|---------------------------|---------------------------------------------|--------------------------------------|------------|
| `/etc/yum.repos.d/`       | Tokens embedded in `baseurl`                | Any build that configures RPM repos  | RHEL       |
|                           |                                             | with authenticated URLs              |            |
| `/etc/pki/entitlement/*`, | Subscription identity                       | If `subscription-manager` ran        | RHEL       |
| `/etc/pki/consumer/*`     |                                             | during the build (BYOL)              |            |
| `/var/log/rhsm/*`         | Subscription manager logs                   | Same as above                        | RHEL       |
| `/root/anaconda-ks.cfg`   | Rendered kickstart with password hashes     | If osbuild produces a                | RHEL       |
|                           |                                             | kickstart-derived artifact           |            |
| `/var/log/anaconda/*`     | Kickstart contents echoed into install logs | Same as above                        | RHEL       |

The cleanup provisioner must run **before snapshot** and should be a pipeline gate, not a convention. If credentials
persist into the image, every instance launched from it carries the same identity.

**Windows images** do not have these paths. The leakage concern for Windows is handled by Sysprep (the final Packer
provisioner), which generalizes the instance and removes machine-specific state.

## Non-Credential Dependencies

Not secrets, but the pipeline fails without them. Easy to overlook during environment setup.

| Item                                 | Needed By                   | Notes                                           |
|--------------------------------------|-----------------------------|-------------------------------------------------|
| Private CA bundle                    | EE, builder instances       | **If** internal services (Artifactory, GitLab,  |
|                                      |                             | Vault) use a private CA, the CA certificate     |
|                                      |                             | must be trusted by the EE and builder           |
|                                      |                             | instances. Without it, TLS connections fail     |
|                                      |                             | with certificate verification errors. Confirm   |
|                                      |                             | with the platform team whether a private CA is  |
|                                      |                             | in use.                                         |
| Packer plugin binaries               | EE or builder instances     | `packer init` fetches plugins from the          |
|                                      |                             | HashiCorp registry (requires outbound HTTPS).   |
|                                      |                             | Builder instances have internet egress, so this |
|                                      |                             | works directly. If egress is ever restricted,   |
|                                      |                             | stage plugin binaries in Artifactory and        |
|                                      |                             | install with `packer plugins install --path`,   |
|                                      |                             | or bake them into the EE.                       |
| GPG public keys for RPM verification | Builder instances (RHEL)    | If RHEL repos are mirrored through Artifactory, |
|                                      |                             | the RPM GPG signing keys need a distribution    |
|                                      |                             | path to the builders for signature              |
|                                      |                             | verification. Not needed if pulling from Red    |
|                                      |                             | Hat CDN directly.                               |
| RHEL content access                  | Builder instances (RHEL)    | osbuild-composer needs access to RHEL package   |
|                                      |                             | repositories to compose images. BYOL; handled   |
|                                      |                             | by the builder's subscription registration.     |
|                                      |                             | Confirm content source: Red Hat CDN (direct,    |
|                                      |                             | builders have egress), Satellite, or            |
|                                      |                             | Artifactory RPM mirror.                         |
| S3 staging bucket                    | `cloud_convert` role (RHEL) | Bucket for qcow2 upload before                  |
|                                      |                             | `ec2:ImportImage`. Must exist before the first  |
|                                      |                             | RHEL build. Should have a lifecycle policy to   |
|                                      |                             | expire staged artifacts.                        |
| `vmimport` service role              | `cloud_convert` role (RHEL) | AWS-managed service role required by            |
|                                      |                             | `ec2:ImportImage`. Must have S3 access to the   |
|                                      |                             | staging bucket. See                             |
|                                      |                             | [AWS VM Import docs](https://docs.aws.amazon.com/vm-import/latest/userguide/required-permissions.html). |

## Content Sources Required

The pipeline needs access to the following types of content. We do not prescribe where these come from; the client may
serve them from Red Hat directly, Satellite, Artifactory mirrors, or another internal source. We need endpoints and
credentials (if any) for each.

| Content type               | Needed by                            | What it is                                               |
|----------------------------|--------------------------------------|----------------------------------------------------------|
| RHEL RPM packages          | osbuild-composer on RHEL builder     | Base OS packages and updates for composing RHEL images   |
| Ansible collections        | Execution environment build, runtime | `ansible.posix`, `community.general`, `amazon.aws`,      |
|                            |                                      |  MindPoint Group STIG, etc.                              |
| Container base images      | Execution environment build          | `ee-minimal-rhel9` or equivalent for building the        |
|                            |                                      | pipeline's EE                                            |
| Packer plugins             | Packer builder                       | `amazon` and `ansible` plugins for Packer (`packer init` |
|                            |                                      | fetches from HashiCorp registry; builders have egress)   |
| SCAP content / datastreams | RHEL builder (offline scan)          | OpenSCAP STIG datastreams for compliance scanning        |
| Windows STIG content       | Packer builder (PowerSTIG)           | PowerSTIG DSC resources for Windows compliance           |

### Common Sources (Reference)

These are typical sources used by other projects. Your environment may differ.

| Content type          | Common source                                | Auth                                          |
|-----------------------|----------------------------------------------|-----------------------------------------------|
| RHEL RPM packages     | Red Hat CDN (via subscription), Satellite,   | Subscription entitlement, Satellite           |
|                       | Artifactory RPM remote                       | registration, or Artifactory token            |
| Ansible collections   | Automation Hub (`console.redhat.com`),       | Offline token (Automation Hub) or none        |
|                       | Galaxy, Artifactory generic repo             | (Galaxy)                                      |
| Container base images | `registry.redhat.io` (authenticated),        | Red Hat service account, or Artifactory token |
|                       | Artifactory Docker remote                    |                                               |
| Packer plugins        | HashiCorp releases                           | None (public), or Artifactory token           |
|                       | (`releases.hashicorp.com`), Artifactory      |                                               |
|                       | generic repo                                 |                                               |
| SCAP content          | `scap-security-guide` RPM (included in RHEL  | Same as RPM access                            |
|                       | repos), or staged in Artifactory             |                                               |
| Windows STIG content  | PowerShell Gallery, or staged in Artifactory | None (public), or Artifactory token           |
