# cloud_validate

Dispatches boot and authenticated SSH validation to the target cloud before Artifactory publication. The builder
always runs on AWS; the validation guest runs in the target cloud. `build_rhel.yml` uses the same stage sequence for
AWS, Azure, and GCP.

## What This Role Does

1. Checks that the selected cloud group and `cloud_target` agree
2. Requires a native image registered from the prepared qcow2 in the current build attempt
3. Clears previous smoke-test evidence and dispatches to the selected provider handler
4. Requires matching successful SSH and cleanup evidence before returning

AWS delegates to [rhel_ami_validate](../rhel_ami_validate/README.md). Azure and GCP have TODO handlers that fail
explicitly until their guest launch, SSH, and cleanup implementations exist. A successful placeholder message cannot
satisfy this role's result checks. These are extension points, not working Azure/GCP cloud integrations.

## Input validation

Ansible validates [the role input contract](meta/argument_specs.yml) at entry. Cloud dispatch uses the same explicit
group-membership pattern as `cloud_convert` and `image_distribute`. Provider-specific inputs and credentials belong
to their implementations; Azure/GCP dispatch does not require AWS guest-validation settings.

## Variables

### Required from inventory (no default)

`cloud_target` is supplied by `cloud_aws.yml`, `cloud_azure.yml`, or `cloud_gcp.yml`.
It must match exactly one supported cloud group.
Builder connectivity and target-cloud guest networking are separate concerns.

### Upstream facts (set by earlier roles)

- `image_build_id` and `build_timestamp`: unique attempt and frozen timestamp from `build_rhel.yml`
- `prepared_qcow2_sha256`: canonical qcow2 checksum from `image_prepare`
- `cloud_image_result`: normalized native image identity from `cloud_convert`

## Provider result contract

Every registration handler must set `cloud_image_result` with these fields:

```yaml
provider: azure
image_id: /subscriptions/.../images/example
location: eastus
build_id: "{{ image_build_id }}"
qcow2_sha256: "{{ prepared_qcow2_sha256 }}"
```

`image_id` identifies the registered native image, not a disk file or storage object. `location` is the AWS source
region, Azure image region, or GCP source project (Compute Engine images are project-scoped). The provider field
matches the target cloud. Provider resource operations and any additional context stay inside provider handlers.

Every validation handler must set `image_validation_result` with those same identity fields plus:

```yaml
target: "{{ inventory_hostname }}"
build_timestamp: "{{ build_timestamp }}"
status: passed
cleanup_status: passed
username: cloud-user
tested_at: "2026-11-09T12:00:00Z"
```

Record passing evidence only after authenticated SSH, expected-user verification, and all temporary-resource cleanup
succeed. Use normal provider login/key provisioning; do not repair the guest's SSH configuration for the test.
Always attempt cleanup after partial launch failures. Retain failed native images for debugging.

`image_validation_gate` checks the native-image evidence before artifact preparation. The producer additionally
checks any source-disk checksum. `artifactory_upload` transfers the selected files, then the playbook explicitly
creates the Release Bundle and invokes `image_release_approve` for native approval and the distribution record.
`image_distribute` checks the provider-neutral record before entering a provider's native approval verification and
copy/share implementation. Provider handlers can be implemented without changing the RHEL playbook or record shape.

## Dependencies

The AWS handler needs the prerequisites documented in `rhel_ami_validate`. Azure/GCP TODOs identify the remaining guest
networking, credentials, native image operations, and cleanup work. Connectivity from the AWS builder to the guest's
SSH endpoint must be supplied for each provider; the framework does not provision cross-cloud networking.

The validation contract is shared with native-image producers, including Windows/Packer. A qcow2 checksum is required
by this conversion path, not by the common publication/distribution roles. OS and tool provenance never select
distribution handlers. See [image_release_approve](../image_release_approve/README.md) for the producer extension
pattern.
