# artifactory_release_bundle

Creates and optionally signs a JFrog Release Bundle v2 that groups all artifacts uploaded under the current
`vm_name/build_timestamp` path into a single distributable unit.

## What This Role Does

1. Sets `vm_name` from `inventory_hostname`
2. Derives the Artifactory repository key and sub-path from `artifactory_image_repo`
3. Sends an AQL-based creation request to the JFrog Lifecycle API (`/lifecycle/api/v2/release_bundle`)
4. Signs the bundle when `release_bundle_signing_key` is configured (skipped if empty)
5. Records `release_bundle_name` and `release_bundle_version` as host facts

The artifact files must already exist in Artifactory; this role sends API requests and does not transfer disk images.
Both build playbooks call this role explicitly after `artifactory_upload` and before `image_release_approve`.
It creates/signs the JFrog bundle only; it does not upload files or emit distribution approval.

## Input validation

Ansible automatically validates [the role input contract](meta/argument_specs.yml) when this role starts.
Defaults remain in `defaults/main.yml`. Semantic and runtime checks remain in tasks; argument validation
accepts some convertible types and does not normalize the variables used by subsequent tasks.

The contract also checks optional `vm_name` overrides before deriving the bundle identity.

Publication requires a non-empty token, endpoint, and repository key before sending API requests.

Before API calls, guards also require an HTTP(S) endpoint with a hostname, the assigned builder, and a non-empty
build timestamp.

## Variables

### Defaults

| Variable                     | Default                           | Description                                    |
|------------------------------|-----------------------------------|------------------------------------------------|
| `artifactory_base_url`       | `https://artifactory.example.com` | Artifactory server URL                         |
| `artifactory_image_repo`     | `libs-release-local/images`       | Repo path; split into repo key + AQL sub-path  |
| `release_bundle_signing_key` | `""`                              | Server-side GPG key alias; empty skips signing |

### Required from inventory (no default)

| Variable                           | Inventory source       | Example  |
|------------------------------------|------------------------|----------|
| `artifactory_token_release_bundle` | vault / AAP credential | (secret) |

### Cross-role (from `group_vars/all.yml`)

| Variable          | Description                                                                  |
|-------------------|------------------------------------------------------------------------------|
| `build_timestamp` | ISO-8601 timestamp shared across `artifactory_upload`, `artifactory_upload`, |
|                   | `cloud_convert`, and this role                                               |

### Upstream facts (set by earlier roles)

| Variable        | Set by             |
|-----------------|--------------------|
| `_builder_host` | `rhel_image_build` |

### Facts set by this role

| Variable                 | Description                                        |
|--------------------------|----------------------------------------------------|
| `release_bundle_name`    | Bundle name (matches `vm_name`)                    |
| `release_bundle_version` | Bundle version (matches `build_timestamp`)         |

## Dependencies

Requires files already uploaded by `artifactory_upload` beneath the same target and timestamp prefix.
