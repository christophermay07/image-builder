# AWS Image Delivery

How finished AMIs are delivered from the build account to consuming accounts, the handoff contract with the receiving
team, and KMS considerations for encrypted images.

**Scope:** The pipeline ends at delivery. Deployment from the delivered AMI (launch templates, autoscaling, instance
configuration) is owned by the receiving team.

## Account Topology

The pipeline assumes a two-account model:

| Account               | Contains                                                                                 |
|-----------------------|------------------------------------------------------------------------------------------|
| **Build account**     | AAP, Vault, Artifactory, builder EC2 instances, IAM roles, built AMIs, S3 staging bucket |
| **Target account(s)** | Where AMIs are delivered for deployment. Owned by a separate team.                       |

Resources in one AWS account are invisible to the other by default. An AMI built in the build account cannot be seen,
launched from, or managed by the target account unless the build account explicitly grants access. Both sides must agree
to the cross-account relationship (an IAM policy on the build side permitting the share, and a trust policy on the
target side permitting the action).

**Single-account simplification:** If everything runs in one account, the delivery step reduces to tagging the AMI. No
cross-account IAM, no KMS key policies, no share/copy mechanics. The `image_distribute` role's cross-account logic is
simply unused.

## Delivery Pattern: Copy

The pipeline uses the **copy** pattern for cross-account AMI delivery. The build account shares the AMI with the target
account, then the target account copies it into a locally-owned AMI.

```
Build Account                              Target Account
┌────────────────┐                        ┌────────────────┐
│  AMI-abc123    │   1. Share             │                │
│  (build owns)  │───────────────────────>│  2. CopyImage  │
│                │                        │  → AMI-xyz789  │
│                │                        │  (target owns) │
└────────────────┘                        └────────────────┘
        │                                         │
  Can deregister                          Independent copy.
  during cleanup.                         Survives build-side
  No impact on                            cleanup.
  target account.
```

### Why Copy, Not Share-Only

The alternative (share without copy) lets the target account launch directly from the build account's AMI. Simpler, but
it creates a **lifecycle coupling**: if the build account deregisters the AMI during routine cleanup, the target
account's launch templates, autoscaling groups, and any automation referencing that AMI ID break silently. The failure
mode is an `InvalidAMIID.NotFound` error at launch time (which may be the first time anyone notices the AMI is gone).

Copy eliminates this coupling. Each account manages its own AMI lifecycle independently. The build account can clean up
old images on its own schedule without coordinating with the target team.

### What the Distribution Role Needs

On the **build account** side (the distribution IAM role):

- `ec2:ModifyImageAttribute`: grant launch permission to the target account
- `ec2:ModifySnapshotAttribute`: grant EBS snapshot access to the target account
- `sts:AssumeRole`: assume a copy role in the target account (if copying on their behalf)

On the **target account** side (a copy role, created by the target team):

- `ec2:CopyImage`: copy the shared AMI into a locally-owned AMI
- `ec2:CreateTags`: tag the copied AMI
- KMS permissions if re-encrypting with a local key (see [KMS Considerations](#kms-considerations))

The trust relationship is **two-sided**: the build account's distribution role must have an IAM policy permitting
`sts:AssumeRole` on the target's copy role ARN, AND the target's copy role must have a trust policy permitting the
build account's distribution role as a principal. If only one side is configured, the error is `AccessDenied` with no
indication of which side is missing.

## Handoff Contract (Decision Required)

When the pipeline finishes, the consuming team needs to know an AMI is ready and how to find it. Three approaches are
viable. They are not mutually exclusive; tagging should happen regardless for Console visibility, and SSM parameters or
notifications can layer on top.

### Option 1: Tag Convention

Every golden AMI is tagged with a documented schema. The consuming team's automation queries for AMIs matching their
desired tags.

**Example tag schema:**

| Tag Key        | Example Value | Purpose                              |
|----------------|---------------|--------------------------------------|
| `golden`       | `true`        | Identifies pipeline-produced images  |
| `os`           | `rhel-9.4`    | OS version                           |
| `profile`      | `base`        | Build profile                        |
| `build_date`   | `2026-10-07`  | When the image was built             |
| `pipeline_run` | `42`          | Traceability back to the build run   |
| `stig_profile` | `stig`        | Which compliance profile was applied |

**Consumer query (AWS CLI):**

```bash
aws ec2 describe-images \
  --owners self \
  --filters "Name=tag:golden,Values=true" \
            "Name=tag:os,Values=rhel-9.4" \
            "Name=tag:profile,Values=base" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
  --output text
```

**Pros:**

- No additional AWS services required.
- Tags are visible in the AWS Console for manual inspection.
- Consumers can filter by any combination of dimensions.

**Cons:**

- Consumers must know and query the tag schema correctly.
- "Latest" requires sorting by creation date; no atomic pointer to the current version.
- Tag schema changes require coordinating with all consumers.

### Option 2: SSM Parameter Store

The pipeline writes the latest AMI ID to a well-known path in AWS Systems Manager Parameter Store. Consumers reference
the parameter path instead of a hardcoded AMI ID or tag query.

**Example parameter paths:**

```
/golden-images/rhel-9.4/base/latest    → ami-0abc123def456
/golden-images/rhel-9.4/database/latest    → ami-0def789abc012
/golden-images/win2022/base/latest     → ami-0ghi345jkl678
```

**Consumer usage (Terraform):**

```hcl
data "aws_ssm_parameter" "golden_ami" {
  name = "/golden-images/rhel-9.4/base/latest"
}

resource "aws_instance" "app" {
  ami = data.aws_ssm_parameter.golden_ami.value
  # ...
}
```

**Consumer usage (CloudFormation):**

```yaml
Parameters:
  AmiId:
    Type: AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>
    Default: /golden-images/rhel-9.4/base/latest
```

**Pipeline requirement:** The distribution role needs `ssm:PutParameter` on the agreed path prefix.

**Pros:**

- Atomic pointer to the current version; no sorting, no tag parsing.
- Native integration with Terraform, CloudFormation, and Launch Templates (resolve at deploy time).
- Parameter history provides an automatic audit trail of AMI ID changes over time.
- Consumers don't need to understand the tag schema.

**Cons:**

- Requires SSM Parameter Store access in the target account.
- If the pipeline writes parameters in the build account, the target account needs cross-account parameter access (or
  the pipeline writes directly to the target account's Parameter Store via the distribution role).
- One more AWS service in the dependency chain.

### Option 3: Notification

The pipeline publishes a notification (SNS topic, email, Slack webhook) when a new AMI is available.

**Pros:**

- Simple to implement.
- Useful for human awareness alongside automated approaches.

**Cons:**

- Not automatable; someone reads the notification and acts on it.
- Breaks when the recipient is unavailable (vacation, team change, channel rename).
- No programmatic way for downstream automation to discover the AMI ID without parsing the notification.
- Does not scale with the number of image variants (10+ notifications per pipeline run).

### Recommendation

**Option 2 (SSM Parameter Store)** is the most operationally robust for automation-driven consumers. It provides an
atomic, programmatic pointer that integrates directly with infrastructure-as-code tools. Option 1 (tags) is a reasonable
standalone choice if the consuming team is not ready to adopt SSM parameters, and should be applied regardless for
Console visibility. Option 3 (notification) works as a supplementary awareness mechanism but should not be the primary
discovery path.

The consuming team should choose based on how their deployment automation currently resolves AMI IDs.

## KMS Considerations

KMS (Key Management Service) manages the encryption keys for EBS volumes and, by extension, AMI snapshots. This section
is relevant when delivering encrypted AMIs across account boundaries.

### Single Account (Current)

If the pipeline and consumers share one AWS account, KMS is largely transparent. EBS volumes and AMI snapshots can use
the default AWS-managed key (`aws/ebs`), and everything works without additional configuration.

### Multi-Account (Future Consideration)

When delivering AMIs across accounts, the encryption key becomes a cross-boundary dependency.

**AWS-managed key (`aws/ebs`):**

- Cannot be shared cross-account. The target account has no access to the build account's AWS-managed key.
- The `CopyImage` operation (Pattern 2) re-encrypts with the target account's own key during the copy. This works, but
  the target account must specify a destination KMS key in the `CopyImage` call.
- Pattern 1 (share-only, without copy) **does not work** with AWS-managed keys because the target account cannot
  decrypt the snapshot.

**Customer-managed key (CMK):**

- Can be shared cross-account by adding the target account to the key policy.
- Required key policy grants for the target account: `kms:Decrypt`, `kms:DescribeKey`, `kms:CreateGrant`.
- Enables both Pattern 1 (direct launch from shared AMI) and Pattern 2 (copy with re-encryption).
- Costs $1/month per key plus per-use API charges (negligible at pipeline volumes).

**Practical guidance:**

- If staying single-account, default encryption is sufficient. No KMS action needed.
- If going multi-account with the copy pattern, re-encryption during copy handles the key boundary. The target account
  specifies their own KMS key as the destination; the copy decrypts with the source key and re-encrypts with the
  destination key.
- The distribution role needs KMS permissions (`kms:Decrypt`, `kms:CreateGrant`) on whatever key encrypts the source
  AMI. The target account's copy role needs KMS permissions on their destination key.
- **Common failure mode:** a cross-account AMI copy or launch fails with a generic `AccessDenied` error that does not
  mention KMS. If IAM permissions look correct but the operation fails, check KMS key policies first; this is the most
  frequently missed piece of cross-account AMI delivery.

## AMI Retention

A cleanup role handles AMI deregistration and snapshot deletion in the build account. By default it retains all AMIs
(retention count defaults to unlimited, date threshold defaults to 2000-01-01). The client adjusts these parameters per
their retention policy.

**With the copy pattern (Pattern 2):** Because the target account owns independent copies, build-side cleanup does not
affect them. The target team manages their own copy retention independently. No cross-team coordination is needed for
routine cleanup.

**If share-only were used (Pattern 1):** The target account would reference AMIs owned by the build account.
Deregistering a shared AMI would break launches on the target side. A formal retention agreement would be required
before running cleanup against shared AMIs.
