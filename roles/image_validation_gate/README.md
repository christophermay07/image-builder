# image_validation_gate

Checks that this attempt's native image has successful validation and guest-cleanup evidence. It performs checks
only; the producer's validator runs the guest tests and cleanup.

Both build playbooks call this gate before preparing and uploading artifacts. `image_release_approve` repeats the
check before granting distribution approval.

## Required inputs

- `_builder_host`, `image_build_id`, and the frozen `build_timestamp`
- `cloud_target`, matching exactly one supported inventory cloud group
- `cloud_image_result`, containing provider, native image ID, location, and build ID
- `image_validation_result`, containing that same identity, target, timestamp, passed validation/cleanup status, and
  test time

The records must describe the same image and current attempt. Missing, stale, cross-target, or cross-provider evidence
fails the gate. A raw AMI ID or existing report files alone cannot satisfy it.

This contract has no OS, build-method, transport, or qcow2 requirement. Producer-specific checks, such as verifying the
prepared qcow2 checksum, belong to the producer's artifact-preparation role.
