# cloud_convert

Converts qcow2 images to cloud-native formats and uploads them.

## What This Role Does

Loops over `cloud_targets` and performs format conversion + upload:

- **AWS:** Upload qcow2 to S3, import as AMI via `ec2_import_image`, tag
- **Azure:** Convert qcow2 to VHD via `qemu-img`, upload (placeholder)
- **GCP:** Convert qcow2 to raw, tar.gz, upload (placeholder)

Since internet is available on first boot, cloud-init installs vendor-specific agents at boot time. This role only
handles format conversion and upload.

## Air-Gapped First Boot (Future)

If deployments lose internet on first boot, this role would need to:
1. Boot the qcow2 on the builder (or use virt-customize)
2. Install vendor agents (AWS SSM Agent, Azure WALinuxAgent, GCP guest-agent)
3. Re-seal the image
4. Convert to the target format

This would produce per-cloud-vendor qcow2s. Not implemented today.

## Variables

| Variable            | Default                                   | Description              |
|---------------------|-------------------------------------------|--------------------------|
| `cloud_targets`     | `[aws]` (v1); azure and gcp commented out | Clouds to convert for    |
| `ami_import_bucket` | `image-pipeline-import`                   | S3 bucket for AMI import |
| `aws_region`        | `us-east-1`                               | AWS region               |

## Dependencies

Requires `image_export` to have completed (compressed qcow2 available).
