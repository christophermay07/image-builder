# image_distribute

Distributes cloud images to target regions/accounts per cloud provider.
Dispatches to provider-specific task files based on `cloud_targets`, mirroring the pattern used by `cloud_convert`.

## What This Role Does

For each cloud in `cloud_targets`:

- **AWS:** Copies the AMI to target regions and shares with target accounts.
- **Azure:** Publishes to Azure Compute Gallery (placeholder; not yet implemented).
- **GCP:** Shares Compute Engine image across projects (placeholder; not yet implemented).

## Variables

### AWS

| Variable              | Default     | Description                       |
|-----------------------|-------------|-----------------------------------|
| `aws_region`          | `us-east-1` | Source AMI region                 |
| `ami_target_regions`  | `[]`        | Regions to copy AMI to            |
| `ami_target_accounts` | `[]`        | Account IDs to share with         |
| `ami_public`          | `false`     | Make AMI public (not recommended) |

### Azure (future)

| Variable                     | Default | Description                    |
|------------------------------|---------|--------------------------------|
| `azure_gallery_name`         | TBD     | Azure Compute Gallery name     |
| `azure_target_subscriptions` | `[]`    | Subscription IDs to share with |

### GCP (future)

| Variable              | Default | Description                   |
|-----------------------|---------|-------------------------------|
| `gcp_target_projects` | `[]`    | GCP project IDs to share with |

## Dependencies

Requires a build or conversion role to have set the appropriate cloud image ID (e.g., `aws_ami_id` or `windows_ami_id`
for AWS).
