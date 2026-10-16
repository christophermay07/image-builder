# image_export

Finalizes the built image: compresses, scans, bundles, and pushes to Artifactory.

## What This Role Does

1. Verifies the qcow2 image exists
2. Compresses the qcow2 (qemu-img convert -c)
3. Generates build metadata JSON (source ISO, STIG profile, timestamp, etc.)
4. Assembles a release bundle: qcow2 + OpenSCAP report + results + metadata
5. Pushes the bundle to Artifactory

## Variables

| Variable                 | Default                        | Description                  |
|--------------------------|--------------------------------|------------------------------|
| `artifactory_base_url`   | `https://artifactory.internal` | Artifactory URL              |
| `artifactory_image_repo` | `libs-release-local/images`    | Target repo path             |
| `artifactory_token`      | _(undefined)_                  | Bearer token for upload      |
| `builder_group`          | _(from method group_vars)_     | Builder group for delegation |

## Dependencies

Requires `cloud_init_prep` to have shut down the VM.
