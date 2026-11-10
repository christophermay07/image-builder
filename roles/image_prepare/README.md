# image_prepare

Compresses the canonical qcow2 before cloud conversion and publication. The source is replaced only after successful
compression, then its SHA-256 checksum is recorded as `prepared_qcow2_sha256`.

## What This Role Does

1. Compresses the builder-local qcow2 with `qemu-img convert -c -O qcow2`
2. Replaces the original after conversion succeeds
3. Records the prepared file checksum for the common cloud publication gate

## Input validation

Ansible validates [the role input contract](meta/argument_specs.yml) on entry. The assigned builder and image output
directory must be non-empty. A missing source image fails conversion before replacement.

## Variables

### Defaults

| Variable           | Default                         | Description              |
|--------------------|---------------------------------|--------------------------|
| `builder_work_dir` | `/var/lib/image-builder`        | Shared builder workspace |
| `image_output_dir` | `{{ builder_work_dir }}/output` | Composed image directory |

### Upstream facts (set by earlier roles)

`_builder_host` is required from `rhel_image_build`. The source filename is derived from `inventory_hostname`.

## Dependencies

Requires an offline, unmounted qcow2 and `qemu-img` on the assigned builder. Run this role before `cloud_convert`
for every provider. Later stages must not modify the prepared qcow2.
