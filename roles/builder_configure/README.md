# builder_configure

Configures persistent EC2 builder instances for the image build pipeline.

## What This Role Does

1. Installs osbuild-composer and composer-cli for RHEL Image Builder
2. Installs validation tools (libguestfs-tools, openscap-scanner) for
   offline compliance scanning of built images
3. Enables the osbuild-composer socket-activated service
4. Creates work directories for blueprints, image output, and reports
5. Installs Packer, Python 3.12, pip, and Git on builders_packer

Ansible and guest-provisioning dependencies are installed by `builder_ansible_prepare` into an isolated environment
for each build. `builder_pip_packages` describes build dependencies; this role no longer
installs them into the builder's global Python or Ansible environment.
`builder_collections` is retained for future callers; Windows preparation currently uses project `requirements.yml`.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

The contract includes retained `builder_pip_packages` and `builder_collections` settings for other consumers.

Before installing packages, guards check native package lists and usable working directories. Packer installation
settings are checked only on Packer builders; the blueprint directory is checked only on osbuild builders.

## Variables

### Defaults

| Variable               | Default                             | Description                          |
|------------------------|-------------------------------------|--------------------------------------|
| `packer_version`       | `1.16.1`                            | Packer version for Windows builds    |
| `packer_binary`        | `/usr/local/bin/packer`             | Installed Packer binary path         |
| `packer_download_url`  | HashiCorp release URL (derived)     | Packer zip download URL              |
| `packer_checksum`      | `sha256:af38a9...`                  | SHA-256 checksum for Packer zip      |
| `builder_work_dir`     | `/var/lib/image-builder`            | Root work directory (cross-role)     |
| `image_output_dir`     | `{{ builder_work_dir }}/output`     | Built image output (cross-role)      |
| `report_output_dir`    | `{{ builder_work_dir }}/reports`    | Compliance reports (cross-role)      |
| `blueprint_dir`        | `{{ builder_work_dir }}/blueprints` | Rendered blueprint TOML files        |
| `builder_packages`     | `[]`                                | osbuild-composer packages per group  |
| `validation_packages`  | `[]`                                | Offline scanning packages per group  |
| `builder_pip_packages` | `[]`                                | Python packages for builder host     |
| `builder_collections`  | `[]`                                | Ansible collections for builder host |

## Dependencies

None.

## Example Usage

```yaml
- hosts: builders
  roles:
    - builder_configure
```
