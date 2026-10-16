# cloud_init_prep

Handles post-compose cloud-init customizations for built RHEL images.

## What This Role Does

With RHEL Image Builder, most cloud-init configuration is handled during the compose via the blueprint:

- **Packages:** cloud-init is a `[[packages]]` entry
- **Datasources:** Multi-cloud datasource list is a `[[customizations.files]]` entry
- **Services:** cloud-init services are enabled via `[customizations.services]`
- **Sealing:** The compose produces a clean image (no prior boot to clean up)

This role handles any cloud-init configuration that cannot be expressed in the blueprint. For most builds, it is a
no-op.

## When This Role Has Work To Do

Set `cloud_init_extra_configs` in profile or host group_vars when you need additional cloud-init config files beyond the
datasource list:

```yaml
cloud_init_extra_configs:
  - filename: 98-custom-modules.cfg
    content: |
      # Custom cloud-init module config
      cloud_final_modules:
        - [scripts-user, always]
```

## Variables

| Variable                   | Default                    | Description                  |
|----------------------------|----------------------------|------------------------------|
| `cloud_init_extra_configs` | `[]`                       | Extra config files to inject |
| `builder_group`            | _(from method group_vars)_ | Builder group for delegation |

## Dependencies

Requires `rhel_image_build` to have produced a qcow2 image. Requires `libguestfs-tools` on the builder (installed by
`builder_configure`).
