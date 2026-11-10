# image_build_initialize

Creates one build-attempt identity and clears state from previous attempts. Both build playbooks call it before
building, including tagged runs. It performs no validation, file upload, or image approval.

## Inputs and outputs

`build_timestamp` comes from inventory and is frozen for the attempt. The role generates `image_build_id` and clears
`cloud_image_result`, `image_validation_result`, `artifactory_upload_artifacts`, `artifactory_upload_result`,
Release Bundle facts, and `published_image`.

It writes an empty global `image_publication_<SHA-256 of inventory_hostname>` artifact for the target. This prevents a
failed attempt from inheriting an earlier approval. The full target name remains in the eventual approved record.

The role has no fallback for a missing timestamp. Its input contract is in `meta/argument_specs.yml`.
