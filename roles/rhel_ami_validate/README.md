# rhel_ami_validate

Boots an imported RHEL AMI and requires authenticated SSH before Artifactory publication. This is a boot and login
smoke test; the existing offline OpenSCAP scan remains the compliance check. This is the AWS implementation invoked
by `cloud_validate/tasks/validate_aws.yml`; the shared RHEL playbook does not select AMI validation directly.

## What This Role Does

1. Marks the AMI unapproved and allocates a private builder-local workspace
2. Generates an RSA-3072 key and imports its public key as a temporary EC2 key pair
3. Launches one instance with a private IP, using the image's normal cloud-init key injection
4. Retries key-authenticated SSH and requires `id -un` to return the configured login user
5. Attempts instance termination, EC2 key deletion, and local workspace removal independently
6. Records passing evidence only after SSH and all cleanup operations succeed

No user-data repairs SSH, creates a login user, or changes guest authentication settings. Keys are never baked into
the qcow2. Each SSH attempt is bounded to 10 seconds; the default total readiness budget is 900 seconds. Host keys
are accepted on the first connection and checked against a dedicated known-hosts file on subsequent attempts.

Failed AMIs and their backing snapshots remain for debugging, tagged `validation_status=failed`. Failed instances are
terminated rather than retained. Successful AMIs receive `validation_status=passed`; publication approval is separate.
The failure message identifies the AMI and failed stage. A cleanup failure blocks publication and lists the failed
cleanup operations. Controller cancellation, an unreachable builder, or AWS API failures can prevent cleanup;
resources carry `purpose=image-builder-validation` and `image_build_id` tags for recovery.

## Input validation

Ansible validates [the role input contract](meta/argument_specs.yml) at entry. Runtime checks require a current build
identity, prepared-image SHA-256, non-empty network settings, a valid login username and port, and a readiness budget
of at least 15 seconds.

## Variables

### Defaults

| Variable                   | Default                  | Description                        |
|----------------------------|--------------------------|------------------------------------|
| `rhel_smoke_instance_type` | `m5.large`               | x86 validation instance type       |
| `rhel_smoke_ssh_user`      | `ec2-user`               | Expected cloud-init login user     |
| `rhel_smoke_ssh_port`      | `22`                     | Guest SSH port                     |
| `rhel_smoke_ssh_timeout`   | `900`                    | SSH readiness budget, seconds      |
| `builder_work_dir`         | `/var/lib/image-builder` | Parent of private test workspaces  |
| `aws_region`               | `us-east-1`              | Region containing the imported AMI |

The optional `aws_build_access_key_id`, `aws_build_secret_access_key`, and `aws_build_session_token` defaults are
empty strings. Empty values use the assigned builder's environment or instance role, as in `cloud_convert`.

### Required from inventory (no default)

Set `rhel_smoke_subnet_id` and `rhel_smoke_security_group_ids` in `group_vars/cloud_aws.yml` or extra-vars. The builder
must reach the guest's private IP on the configured SSH port. Supply existing subnet and security group IDs; the role
does not create networking or assign a public IP. The guest needs access to any services required by normal first boot.

### Upstream facts (set by earlier roles)

- `_builder_host`: assigned builder from `rhel_image_build`
- `aws_ami_id` and `cloud_image_result`: imported image and source checksum binding from `cloud_convert`
- `image_build_id` and `build_timestamp`: unique attempt and frozen timestamp from `build_rhel.yml`
- `prepared_qcow2_sha256`: canonical file checksum from `image_prepare`

The output `image_validation_result` records target, attempt, timestamp, provider=`aws`, native `image_id`,
source `location`,
checksum, login user, test time, and passing SSH/cleanup status. `image_validation_gate` requires matching evidence;
the producer verifies its qcow2 checksum again before constructing the upload manifest.

## Dependencies

The builder needs `openssh-clients` (`ssh`, `ssh-keygen`) and `coreutils` (`timeout`), installed by
`builder_configure` through the osbuild builder package list. The outer execution environment needs `amazon.aws`.
No separate guest machine credential is required; the existing builder machine credential reaches the builder.

The build AWS identity needs the existing S3 and VM Import permissions plus `ec2:RunInstances`,
`ec2:TerminateInstances`, `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`, `ec2:ImportKeyPair`,
`ec2:DeleteKeyPair`, `ec2:DescribeKeyPairs`, `ec2:CreateTags`, and the EC2 describe permissions used when resolving
images, instance types, networking, and volumes. Include KMS permissions if the AMI uses encrypted snapshots.
Scope permissions to the validation network and tagged resources where supported.
