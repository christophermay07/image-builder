# cloud_convert

Converts qcow2 images to cloud-native formats and uploads them.

## What This Role Does

Dispatches to provider-specific task files based on cloud group membership (e.g., `'cloud_aws' in group_names`):

- **AWS:** Convert qcow2 to raw, upload raw to S3, import as AMI via `ec2_import_image`, tag as pending validation
- **Azure:** Convert qcow2 to VHD via `qemu-img`, then stop at the native registration TODO
- **GCP:** Convert qcow2 to raw/tar.gz, then stop at the native registration TODO

Today cloud-init installs vendor-specific agents (AWS SSM Agent, Azure WALinuxAgent, GCP guest-agent) on first boot.
This role handles conversion, upload, and native image registration; guest validation is a separate stage.

## Vendor Agents Without Outbound Internet (Future)

FedRAMP environments sometimes block outbound internet from VMs while still providing connectivity to cloud-provider
APIs (via VPC endpoints, Private Link, etc.). If the target environment lacks outbound internet, cloud-init cannot pull
packages from public repos at first boot.

Likely solutions, in order of preference:

1. **Internal package mirror**: point cloud-init at a Satellite server or internal repo inside the environment. Nothing
   changes in this role or in osbuild; only the cloud-init config needs a repo URL.
2. **`virt-customize` post-build**: copy the base qcow2 per cloud target, inject only that cloud's agent package, then
   convert. This would add a pre-conversion step to this role.
3. **Per-cloud osbuild blueprints**: run the full build once per target cloud. Correct but expensive.

Option 2 is the only one that changes this role. If we get there, the workflow becomes: copy qcow2 per target,
`virt-customize --install <agent>`, then convert and upload as today.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Shared path defaults, composed tag inputs, and optional target-name overrides are included in the contract.

The target must belong to exactly one supported cloud group. Before conversion, guards check the builder, input
directory, and source image file. AWS-only inputs are checked inside the AWS branch before upload or import.

## Variables

### Defaults

| Variable                      | Default                           | Description                            |
|-------------------------------|-----------------------------------|----------------------------------------|
| `ami_import_bucket`           | `image-pipeline-import`           | S3 bucket for AMI import               |
| `builder_work_dir`            | `/var/lib/image-builder`          | Base working directory (cross-role)    |
| `image_output_dir`            | `{{ builder_work_dir }}/output`   | Built-image output path (cross-role)   |
| `aws_region`                  | `us-east-1`                       | AWS region (cross-role)                |
| `aws_build_access_key_id`     | `""`                              | AWS access key for build operations    |
| `aws_build_secret_access_key` | `""`                              | AWS secret key for build operations    |
| `aws_build_session_token`     | `""`                              | AWS session token for build operations |

### Required from inventory (no default)

| Variable       | Inventory source   | Example |
|----------------|--------------------|---------|
| `cloud_target` | `cloud_*.yml`      | `aws`   |
| `profile`      | `profile_*.yml`    | `base`  |
| `os_version`   | `rhel_*_*.yml`     | `9.4`   |
| `os_family`    | `rhel_targets.yml` | `rhel`  |

Cloud dispatch is based on group membership (`'cloud_aws' in group_names`),
not a variable.

### Cross-role (from `group_vars/all.yml`)

| Variable          | Description                                                  |
|-------------------|--------------------------------------------------------------|
| `ami_base_tags`   | Canonical AMI tags combined with build and validation status |
| `build_timestamp` | ISO-8601 timestamp; referenced inside `ami_base_tags`        |

### Upstream facts (set by earlier roles)

| Variable         | Set by             |
|------------------|--------------------|
| `_builder_host`  | `rhel_image_build` |

## Dependencies

Requires `image_prepare` to have completed (compressed qcow2 and checksum available). Every provider uses the current
`image_build_id` from `build_rhel.yml`. The import task name, S3 prefix, and local raw filename include that unique ID.
Local raw staging is removed after import, including on failure. S3 objects are retained for diagnosis; configure
bucket lifecycle expiration for staging objects. Provision enough builder disk capacity for the raw disk's contents.

The AWS branch uses the pinned collection's nested `import_image.import_task_id` result and stops polling on terminal
failure statuses, reporting the import status message. On success, `aws_ami_id` is set and the image is tagged pending
validation and publication. It must pass `cloud_validate` (which selects `rhel_ami_validate` for AWS)
before the validation gate and explicit artifact-upload stage.

## Provider extension points

Every provider returns the same `cloud_image_result`: `provider`, native `image_id`, source `location`, `build_id`, and
`qcow2_sha256`. The role checks this record after registration. `cloud_target` is required and must match the selected
cloud group. See [cloud_validate](../cloud_validate/README.md) for field semantics and validation outputs.

Azure/GCP handlers include TODOs for native upload/registration and deliberately fail before publication. They do not
return storage-object paths as image identities. Azure VHD and GCP archive filenames include the unique build ID.
GCP stages `disk.raw` in a private attempt-specific directory and removes it even after conversion/archive failure.
Complete the TODO handlers rather than changing the ordering in `build_rhel.yml`.
