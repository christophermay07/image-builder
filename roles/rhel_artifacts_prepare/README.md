# rhel_artifacts_prepare

Prepares the RHEL qcow2/OpenSCAP artifact set for publication. The playbook calls this role after cloud validation
and `image_validation_gate`, before `artifactory_upload`.

The role verifies that the qcow2 still matches the prepared and validated SHA-256, generates build metadata, and
sets `artifactory_upload_artifacts` to four builder-local files:

- The golden qcow2, uploaded as `<target>.qcow2`
- OpenSCAP HTML and XML evidence, uploaded as `oscap-report.html` and `oscap-results.xml`
- Generated metadata, uploaded as `build-metadata.json`

It reads the existing output/report directories directly. It performs no composition, cloud operations, upload,
bundling, or release approval.

Required context includes `_builder_host`, the frozen `build_timestamp`, native image and validation records,
`prepared_qcow2_sha256`, and OS/method/profile/cloud provenance. Paths default beneath `builder_work_dir` as in the
build pipeline. Metadata retains the producer's calendar-version and STIG-profile defaults; inventory and caller
overrides take precedence. See `meta/argument_specs.yml` for required and optional inputs.

The metadata template belongs to this role. `rhel_image_build` owns composition; `artifactory_upload` owns transfer.
Future producers may reuse preparation when their artifact and metadata contracts match. Sharing an OS or build
method alone does not establish that compatibility.
