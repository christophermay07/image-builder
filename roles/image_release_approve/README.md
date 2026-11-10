# image_release_approve

Approves a successfully published native image for distribution and emits its common approved record.
It does not initialize builds, generate metadata, upload files, or create Release Bundles.

## Approval sequence

1. Recheck this attempt's evidence through `image_validation_gate`
2. Require `artifactory_upload_result` to confirm uploads for this target and frozen timestamp
3. Require the matching `release_bundle_name` and `release_bundle_version` from `artifactory_release_bundle`
4. Record provider-native approval (AWS implemented; Azure/GCP remain explicit TODO failures)
5. Emit `published_image` and the target's global AAP artifact only after every preceding step succeeds

## Required context

The role uses the same native identity and validation inputs as `image_validation_gate`. It also requires
`artifactory_upload_result`, Release Bundle facts, and `os_family`, `os_version`, `build_method`, and `profile`
provenance.
AWS build credential overrides default to empty strings, using the assigned builder's environment or instance role.
Azure/GCP approval handlers require implementation before those providers can grant approval.

`cloud_image_result` contains `provider`, native `image_id`, source `location`, and `build_id`. Location is the AWS
region, Azure image region, or GCP source project. A storage object or disk filename is not a native image ID.

`image_validation_result` contains the same identity plus target, build timestamp, passed validation/cleanup status,
and test time. Validators choose OS-appropriate checks. A qcow2 checksum, username, or validation method may be
included as provenance; distribution requires no particular disk format or guest protocol.

## Output and AAP handoff

`published_image` adds published status, builder identity, and OS/method/profile provenance to the validation record.
Each target emits a distinct global artifact named `image_publication_<SHA-256 of inventory_hostname>`, containing
that complete record. The data-key prefix is retained even though the role names changed.

`per_host: false` makes the record available to downstream AAP jobs; `aggregate: false` replaces the target's empty
initialization record. The target name inside the record is checked when consuming it. Hashing gives a deterministic,
valid variable name without collisions caused by sanitizing target names.

Distinct top-level keys preserve records from parallel producer jobs at workflow convergence. See
[AAP workflow guidance](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.4/html/automation_controller_user_guide/controller-workflows).
A workflow must assign each target to one producer. Failed attempts leave an empty record. `image_distribute` prefers
an in-process `published_image` fact and otherwise restores the target's unique artifact. Raw AMI facts cannot bypass
approval.

## Adding a producer

Use the explicit sequence shown in both build playbooks:

```text
image_build_initialize
→ OS/method-specific build and registration
→ OS/provider-specific validation and cleanup
→ image_validation_gate
→ producer artifact-preparation role
→ artifactory_upload
→ artifactory_release_bundle
→ image_release_approve
```

The producer supplies native identity, validation evidence, metadata generation, and its artifact list. Build tools
that already produce native images skip conversion. Adding an OS or build method requires no upload or distribution
branches; adding a target cloud requires its provider-specific registration, validation, approval, and distribution
handlers.
