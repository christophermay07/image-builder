# ami_cleanup

Deregisters old AMIs and deletes their backing EBS snapshots based on age and count retention policies.

## What This Role Does

Dispatches to provider-specific task files based on cloud group membership (e.g., `'cloud_aws' in group_names`),
following the same pattern as `cloud_convert` and `image_distribute`.

For **AWS**:

1. Builds the list of regions to clean (source region plus any `ami_target_regions`)
2. Queries AMIs owned by `self` with a `Name` tag matching `vm_name` in each region
3. Filters AMIs for deletion using two independent rules (an AMI is deleted if either condition is true):
   - Its `creation_date` is before `ami_cleanup_older_than`
   - It exceeds the `ami_cleanup_keep_count` ceiling (after date-expired AMIs are removed)
4. Deregisters each qualifying AMI and deletes its backing EBS snapshots

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Optional target-name overrides are checked even though `vm_name` normally comes from the inventory hostname.

AWS cleanup also requires a retention count of `-1` or a nonnegative integer and a valid `YYYY-MM-DD` cutoff.

Before querying deletion candidates, guards require a literal target name without `*` or `?`, a non-empty source
region, and a native list of non-empty additional regions.

## Variables

### Defaults

| Variable                        | Default      | Description                                       |
|---------------------------------|--------------|---------------------------------------------------|
| `ami_cleanup_keep_count`        | `-1`         | Most-recent AMIs to keep per host per region;     |
|                                 |              | `-1` disables count-based cleanup                 |
| `ami_cleanup_older_than`        | `2000-01-01` | ISO date; AMIs created before this are deleted;   |
|                                 |              | far-past default effectively disables date filter |
| `aws_region`                    | `us-east-1`  | Source AMI region                                 |
| `ami_target_regions`            | `[]`         | Additional regions with cross-region AMI copies   |
| `aws_cleanup_access_key_id`     | `""`         | AWS access key for cleanup operations             |
| `aws_cleanup_secret_access_key` | `""`         | AWS secret key for cleanup operations             |
| `aws_cleanup_session_token`     | `""`         | AWS session token for cleanup operations          |

### Upstream facts (set within this role)

| Variable  | Description                                            |
|-----------|--------------------------------------------------------|
| `vm_name` | Set from `inventory_hostname`; used as AMI name filter |

## Dependencies

None. This role runs independently of the build pipeline and can target any region where AMIs were previously
published.
