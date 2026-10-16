# builder_configure

Configures persistent EC2 builder instances for the image build pipeline.

## What This Role Does

1. Installs osbuild-composer and composer-cli for RHEL Image Builder
2. Installs validation tools (libguestfs-tools, openscap-scanner) for
   offline compliance scanning of built images
3. Enables the osbuild-composer socket-activated service
4. Creates work directories for blueprints, image output, and reports
5. Installs Packer on packer_builders (for Windows AMI builds)

## Variables

| Variable              | Default                               | Description                       |
|-----------------------|---------------------------------------|-----------------------------------|
| `builder_work_dir`    | `/var/lib/image-builder`              | Root work directory               |
| `blueprint_dir`       | `{{ builder_work_dir }}/blueprints`   | Rendered blueprint TOML files     |
| `image_output_dir`    | `{{ builder_work_dir }}/output`       | Built image output                |
| `report_output_dir`   | `{{ builder_work_dir }}/reports`      | Compliance reports                |
| `builder_packages`    | _(see defaults)_                      | osbuild-composer packages         |
| `validation_packages` | _(see defaults)_                      | Offline scanning packages         |
| `packer_version`      | `1.16.1` _(from packer_builders.yml)_ | Packer version for Windows builds |

## Dependencies

None.

## Example Usage

```yaml
- hosts: builders
  roles:
    - builder_configure
```
