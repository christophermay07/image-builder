# windows_ami_validate

Boots a fresh EC2 instance from a newly created Windows AMI and runs a post-AMI PowerSTIG compliance scan to validate
the shipped artifact.

## Why This Exists

The pre-seal PowerSTIG scan (in `windows_compliance_scan`) runs inside the Packer guest before Sysprep. It catches
hardening failures early, but it does not evaluate the production artifact. Between the pre-seal scan and the AMI
snapshot, the pipeline applies deferred STIG rules, runs Sysprep generalization, and snapshots the result. The post-AMI
scan verifies that the actual shipped AMI passes compliance.

See ADR-IB-031 for the full rationale.

## What This Role Does

1. Launches a fresh EC2 instance from `windows_ami_id`
2. Bootstraps WinRM HTTPS via userdata (new password, self-signed cert)
3. Waits for WinRM connectivity
4. Runs PowerSTIG against the live instance
5. Downloads results to the builder host (prefixed `post-seal-`)
6. Terminates validation instances by the unique attempt tag and waits for termination, including on launch failure
7. Records the common successful validation/cleanup evidence only after all validation and cleanup tasks succeed

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

The contract checks alias source settings as well as effective `validate_*` values; sources stay optional.

WinRM ports must be integers from 1 to 65535; readiness timeouts must be positive integers.

Before writing provisioner files or launching a guest, guards check the AMI, builder workspace, scan settings, and
non-empty guest password. Result prefixes must be simple basenames; manifest hashes must be empty or 64 hex digits.

## Variables

### Defaults

| Variable                           | Default                          | Description                             |
|------------------------------------|----------------------------------|-----------------------------------------|
| `validate_instance_type`           | `m5.large`                       | EC2 instance type for validation        |
| `validate_winrm_timeout`           | `900`                            | Seconds to wait for WinRM               |
| `validate_winrm_port`              | `5986`                           | WinRM HTTPS port on validation instance |
| `validate_compliance_output_dir`   | `C:\compliance-results`          | Result path inside the validation VM    |
| `validate_generate_html`           | `true`                           | Generate HTML summary report            |
| `validate_result_prefix`           | `post-seal`                      | Filename prefix for scan results        |
| `validate_powerstig_version`       | `{{ powerstig_version }}`        | PowerSTIG version (windows_targets.yml) |
| `validate_powerstig_stig_id`       | `{{ powerstig_stig_id }}`        | STIG checklist ID (windows_*.yml)       |
| `validate_powerstig_manifest_hash` | `{{ powerstig_manifest_hash }}`  | PowerSTIG manifest SHA-256 hash         |
| `validate_nuget_provider_version`  | `{{ nuget_provider_version }}`   | NuGet provider version                  |
| `builder_work_dir`                 | `/var/lib/image-builder`         | Base working directory (cross-role)     |
| `report_output_dir`                | `{{ builder_work_dir }}/reports` | Report output path (cross-role)         |
| `aws_region`                       | `us-east-1`                      | AWS region (cross-role)                 |
| `aws_build_access_key_id`          | `""`                             | AWS access key for build operations     |
| `aws_build_secret_access_key`      | `""`                             | AWS secret key for build operations     |
| `aws_build_session_token`          | `""`                             | AWS session token for build operations  |

### Required from inventory (no default)

| Variable               | Inventory source   | Example  |
|------------------------|--------------------|----------|
| `winrm_admin_password` | vault / extra-vars | (secret) |

The default password alias uses `winrm_admin_password`. The checklist alias requires `powerstig_stig_id` from
`windows_*.yml` unless `validate_powerstig_stig_id` is explicitly supplied. The other module-setting aliases retain
inline fallbacks documented in `defaults/main.yml`.

### Upstream facts (set by earlier roles)

| Variable         | Set by                                 |
|------------------|----------------------------------------|
| `windows_ami_id` | `windows_image_build`                  |
| `_builder_host`  | `windows_image_build`                  |

## Dependencies

- `windows_image_build` must have run first (sets `windows_ami_id` and `_builder_host`)
- AWS credentials must be available (reuses `aws_build_*` variables)

## Output

Results are saved to `{{ report_output_dir }}/{{ vm_name }}/`:

- `post-seal-stig-results.json`: structured per-rule pass/fail results
- `post-seal-stig-report.html`: color-coded summary table

## Builder-side handoff

Validation reuses the isolated Ansible executable, configuration, collections, and project roles prepared by
`windows_image_build`. It writes resolved `validate_*` settings to `validation.yml`; the guest credentials go into a
separate restricted inventory file. Neither file is passed as inline command-line credentials.

Both validation playbooks are syntax-checked before launching the validation instance. WinRM readiness and scan
failures trigger instance termination. Results produced by the shared scan role with `pre-seal-` names are fetched
under the configured `validate_result_prefix` so they remain distinct from build-instance evidence.
The outer build play removes the workspace after all consumers finish. HTML results are fetched only when enabled.

The checklist alias `validate_powerstig_stig_id` references the required version-specific `powerstig_stig_id` without
an OS-release fallback. Standalone validation callers must supply that input or an explicit validation checklist.

The role requires `image_build_id`, `build_timestamp`, and this attempt's `cloud_image_result` from the producer.
Its `image_validation_result` uses the same native identity and validation/cleanup status as other OS validators.
It records `validation_method: winrm-fips-stig`; no qcow2 checksum is required.
A launch, readiness, scan, download, or cleanup failure prevents success from being recorded.
Distribution therefore needs no Windows-specific path.
