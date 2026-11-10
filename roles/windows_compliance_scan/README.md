# windows_compliance_scan

Runs a pre-seal PowerSTIG compliance scan inside the Windows Packer guest after STIG remediation and before Sysprep.

## What This Role Does

1. Creates the compliance output directory on the Windows guest
2. Installs the NuGet package provider
3. Installs the PowerSTIG module at the pinned version
4. Verifies the PowerSTIG module manifest hash (when `powerstig_manifest_hash` is set)
5. Runs a PowerSTIG audit in test mode and exports results to JSON
6. Generates an HTML compliance report (when `compliance_generate_html` is true)

This is a build-time diagnostic that catches hardening failures early. Output files are prefixed `pre-seal-` to
distinguish them from the post-AMI scan produced by `windows_ami_validate`. See ADR-IB-031.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

Before creating output directories or installing modules, guards require non-empty module versions and an output
directory. A configured manifest hash must contain exactly 64 hexadecimal digits; empty still skips verification.

## Variables

### Defaults

| Variable                   | Default                 | Description                                   |
|----------------------------|-------------------------|-----------------------------------------------|
| `powerstig_version`        | `4.30.0`                | PowerSTIG module version to install           |
| `powerstig_manifest_hash`  | `""`                    | SHA-256 of PowerSTIG.psd1; empty skips verify |
| `nuget_provider_version`   | `2.8.5.201`             | NuGet package provider version                |
| `compliance_output_dir`    | `C:\compliance-results` | Output directory on the Windows guest         |
| `compliance_generate_html` | `true`                  | Generate HTML summary report                  |

Module settings come from `group_vars/windows_targets.yml` and are also used by `windows_ami_validate`.
The output directory and HTML toggle are role-local settings; hardening does not consume these scan settings.

### Required from inventory (no default)

| Variable            | Inventory source | Example                 |
|---------------------|------------------|-------------------------|
| `powerstig_stig_id` | `windows_*.yml`  | `WindowsServer-2022-MS` |

The caller must supply `powerstig_stig_id` from the target Windows version inventory. There is no Server 2022
fallback; a missing checklist fails before scan operations. The outer build supplies it through the scan payload.

## Dependencies

Requires `windows_hardening` to have completed STIG remediation on the guest. Scan results are consumed downstream by
`artifactory_upload`, which uploads them to Artifactory.
