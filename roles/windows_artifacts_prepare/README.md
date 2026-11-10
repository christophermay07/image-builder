# windows_artifacts_prepare

Prepares the Windows pre/post-image compliance artifact set for publication. The playbook calls this role after
post-AMI validation and `image_validation_gate`, before `artifactory_upload`.

The role generates build metadata and sets `artifactory_upload_artifacts` to six builder-local files beneath
`<report_output_dir>/<target>/`:

- `pre-seal-stig-results.json` and `pre-seal-stig-report.html`
- `post-seal-stig-results.json` and `post-seal-stig-report.html`
- `fips-verify.json`
- `build-metadata.json`

Destination filenames match these basenames. The native image stays in the cloud. This role performs no Packer
build, guest validation, cloud operations, upload, bundling, or release approval.

Required context includes `_builder_host`, the frozen `build_timestamp`, native image and validation records, and
OS/method/profile/cloud provenance. `report_output_dir` defaults beneath `builder_work_dir`. Optional source-image,
image-version, and STIG-role provenance retain the metadata template's existing fallbacks. See
`meta/argument_specs.yml` for the input contract. Packer settings and guest/cloud credentials are unnecessary.

The metadata template belongs to this role. `windows_image_build` owns building; `artifactory_upload` owns transfer.
Future producers may reuse preparation when their artifact and metadata contracts match. Sharing an OS or build
method alone does not establish that compatibility.
