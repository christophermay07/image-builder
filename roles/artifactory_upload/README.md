# artifactory_upload

Uploads the explicit files selected by a producer. The role performs file transfer and upload preflight only.
It does not choose OS-specific reports, generate metadata, create a Release Bundle, validate a guest, or approve an
image for distribution.

Both build playbooks use the same uploader after their validation gate and artifact-preparation stage.

## Inputs

`_builder_host` identifies the Linux builder holding the files. `build_timestamp`, `artifactory_base_url`,
`artifactory_image_repo`, and `inventory_hostname` determine the existing remote build prefix:

```text
<artifactory_base_url>/<artifactory_image_repo>/<target>/<build_timestamp>/<name>
```

The endpoint defaults to `https://artifactory.example.com`, and the repository to `libs-release-local/images`.
The caller must supply `artifactory_upload_token` and a non-empty `artifactory_upload_artifacts` list:

```yaml
artifactory_upload_artifacts:
  - src: /var/lib/image-builder/output/example.qcow2
    name: example.qcow2
  - src: /var/lib/image-builder/reports/example-build-metadata.json
    name: build-metadata.json
```

Each `src` must be an absolute builder-local regular-file path; symlinks to regular files are accepted. Destination
names must be unique filename-safe basenames. The complete list is checked before the first HTTP request.
Uploads use sequential authenticated PUT requests delegated to the builder, accepting HTTP 201 as before. A failed
request stops the pipeline; completed uploads are not rolled back.

Both build playbooks use `artifactory_upload_token` directly for images, compliance reports, and metadata.
Inventory defaults it to the shared `artifactory_token` injected by AAP/Vault. Set `artifactory_upload_token`
explicitly to use a separate upload identity. Release Bundle creation/signing uses `artifactory_token_release_bundle`.

## Output

`artifactory_upload_result` is set only after all files succeed. It records the target, frozen timestamp, uploaded
status, and destination filenames. Release approval requires this receipt and the matching Release Bundle facts.
The uploader clears a previous receipt before starting its requests; build initialization also clears it.

## Producer responsibilities

Each producer calls a separate artifact-preparation role to generate metadata and set the file list.
[`rhel_artifacts_prepare`](../rhel_artifacts_prepare/README.md) includes the validated qcow2 and OpenSCAP evidence;
[`windows_artifacts_prepare`](../windows_artifacts_prepare/README.md) includes pre/post-AMI reports, FIPS output, and
metadata. The uploader's code is identical for both lists and for future artifact types. Reuse preparation when the
artifact and metadata contracts match; otherwise add a preparation role for the new producer.

Future pipelines must call `image_validation_gate` before preparation/upload, then `artifactory_release_bundle` and
`image_release_approve` after successful upload. Native images remain in their target cloud; including a disk file in
the manifest is optional.
