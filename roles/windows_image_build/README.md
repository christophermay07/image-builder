# windows_image_build

Builds Windows Server images using Packer with an Ansible provisioner.

Currently uses the Packer `amazon-ebs` builder for AWS AMIs. Future: will add `azure-arm` and `googlecompute` sources
for Azure and GCP.

## What This Role Does

1. Templates a Packer HCL configuration from the source image
2. Templates a Packer variables file with profile-specific settings
3. Runs `packer init` to fetch required plugins
4. Runs `packer build` which:
   - Launches a cloud instance from the source image
   - Hands off to an Ansible provisioner for hardening/customization
   - Runs a pre-seal PowerSTIG scan (build-time diagnostic)
   - Generalizes via Sysprep and captures the result as a new cloud image
5. Extracts the output image ID for distribution

After this role completes, `windows_ami_validate` boots a fresh instance from the
registered AMI and runs a post-AMI PowerSTIG scan to validate the shipped artifact.
See ADR-IF-031 for the rationale.

## Variables

### AWS (current)

| Variable               | Default                     | Description                 |
|------------------------|-----------------------------|-----------------------------|
| `source_ami`           | _(from version group_vars)_ | Source Windows AMI          |
| `packer_instance_type` | `m5.xlarge`                 | EC2 instance type for build |
| `packer_binary`        | `/usr/local/bin/packer`     | Path to Packer binary       |
| `aws_region`           | `us-east-1`                 | AWS region                  |

### Azure (future)

| Variable             | Default | Description                    |
|----------------------|---------|--------------------------------|
| `azure_source_image` | TBD     | Source Windows image reference |
| `azure_vm_size`      | TBD     | VM size for build              |

### GCP (future)

| Variable           | Default | Description            |
|--------------------|---------|------------------------|
| `gcp_source_image` | TBD     | Source Windows image   |
| `gcp_machine_type` | TBD     | Machine type for build |

## Dependencies

Requires `builder_configure` to have installed Packer on the builder.
