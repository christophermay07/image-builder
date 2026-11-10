# image_distribute

Distributes cloud images to target regions/accounts per cloud provider.
Dispatches to provider-specific task files based on cloud group membership
(e.g., `'cloud_aws' in group_names`), mirroring the pattern used by `cloud_convert`.

## What This Role Does

For the phantom host's cloud group:

- **AWS:** Copies the AMI to target regions and shares with target accounts.
- **Azure:** Publishes to Azure Compute Gallery (placeholder; not yet implemented).
- **GCP:** Shares Compute Engine image across projects (placeholder; not yet implemented).

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Cloud metadata inputs and optional target-name overrides are included in the contract.

The target must belong to exactly one supported cloud group. AWS distribution checks native target lists, non-empty
region names, and quoted 12-digit account IDs before copying or sharing. Azure and GCP branches require no AWS inputs.

## Variables

### Defaults

| Variable                           | Default     | Description                                 |
|------------------------------------|-------------|---------------------------------------------|
| `aws_region`                       | `us-east-1` | Source AMI region                           |
| `ami_target_regions`               | `[]`        | Regions to copy AMI to                      |
| `ami_target_accounts`              | `[]`        | Account IDs to share with                   |
| `aws_distribute_access_key_id`     | `""`        | AWS access key for distribute operations    |
| `aws_distribute_secret_access_key` | `""`        | AWS secret key for distribute operations    |
| `aws_distribute_session_token`     | `""`        | AWS session token for distribute operations |

### Required from inventory (no default)

| Variable       | Inventory source | Example |
|----------------|------------------|---------|
| `cloud_target` | `cloud_*.yml`    | `aws`   |
| `os_version`   | `rhel_*_*.yml`   | `9.4`   |
| `profile`      | `profile_*.yml`  | `base`  |

### Publication input

`published_image` is the approved record from `image_release_approve` in the same process. It has no default, allowing
separate AAP jobs to restore the target's unique `image_publication_<target SHA-256>` artifact. An empty in-process
record deliberately takes precedence over inherited artifacts after a failed attempt.

The record supplies native image ID, provider, source location, build identity, builder, and successful validation,
cleanup, and publication status. OS, version, profile, and build method are provenance; they never select a
branch. Neither a qcow2 checksum nor an OS-specific raw AMI fact is required or accepted as a substitute.

### Azure / GCP (future, not yet in defaults)

Azure/GCP handlers contain TODOs for native approval verification and sharing, and fail until implemented.
Provider-specific settings belong in cloud inventory and role defaults when their handlers are implemented.

## Dependencies

Every producer must complete the [common publication contract](../image_release_approve/README.md), including Windows
and future OS/build methods. Targets without approved records are skipped. The distribution job needs the builder
machine credential because AWS verification and copy/share operations execute on the recorded builder.

## Distribution flow

`distribute_published.yml` selects the record; `validate_publication.yml` checks approval and restores builder context.
`dispatch.yml` selects only by cloud group. AWS uses `verify_aws.yml` to check source availability and matching
`image_build_id`, `validation_status=passed`, and `publication_status=published` tags before `distribute_aws.yml`
creates copies or launch permissions. The distribution identity needs `ec2:DescribeImages` as well as copy/share
permissions.

Adding an OS or build method requires no distribution branch. Add a provider handler only when the native cloud API
or image type requires different verification and delivery operations. There is no fallback from an absent approved
record to `aws_ami_id` or `windows_ami_id`.
