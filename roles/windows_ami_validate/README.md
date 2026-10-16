# windows_ami_validate

Boots a fresh EC2 instance from a newly created Windows AMI and runs a post-AMI PowerSTIG compliance scan to validate
the shipped artifact.

## Why This Exists

The pre-seal PowerSTIG scan (in `windows_compliance_scan`) runs inside the Packer guest before Sysprep. It catches
hardening failures early, but it does not evaluate the production artifact. Between the pre-seal scan and the AMI
snapshot, the pipeline applies deferred STIG rules, runs Sysprep generalization, and snapshots the result. The post-AMI
scan verifies that the actual shipped AMI passes compliance.

See ADR-IF-031 for the full rationale.

## What This Role Does

1. Launches a fresh EC2 instance from `windows_ami_id`
2. Bootstraps WinRM HTTPS via userdata (new password, self-signed cert)
3. Waits for WinRM connectivity
4. Runs PowerSTIG against the live instance
5. Downloads results to the builder host (prefixed `post-seal-`)
6. Terminates the validation instance (always, even on scan failure)

## Variables

| Variable                     | Default                   | Description                                  |
|------------------------------|---------------------------|----------------------------------------------|
| `windows_ami_id`             | _(set by upstream role)_  | AMI ID to validate                           |
| `validate_instance_type`     | `m5.large`                | EC2 instance type for validation             |
| `validate_winrm_timeout`     | `900`                     | Seconds to wait for WinRM                    |
| `validate_powerstig_version` | `{{ powerstig_version }}` | PowerSTIG version (from windows_targets.yml) |
| `validate_powerstig_stig_id` | `{{ powerstig_stig_id }}` | STIG checklist ID (from windows_targets.yml) |
| `validate_result_prefix`     | `post-seal`               | Filename prefix for scan results             |
| `packer_winrm_password`      | _(from inventory/vault)_  | Password for validation bootstrap            |

## Dependencies

- `windows_image_build` must have run first (sets `windows_ami_id` and `_builder_host`)
- AWS credentials must be available (reuses `aws_build_*` variables)

## Output

Results are saved to `{{ report_output_dir }}/{{ vm_name }}/`:

- `post-seal-stig-results.json`: structured per-rule pass/fail results
- `post-seal-stig-report.html`: color-coded summary table
