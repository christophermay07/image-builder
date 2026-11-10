# Ansible Windows Connection: WinRM / PSRP / SSH

## Purpose

This document evaluates the three Ansible connection options for managing Windows Server 2022 and 2025 hosts --
legacy WinRM, PSRP, and SSH -- with a focus on FIPS 140-3 compliance and DISA STIG requirements. It covers two
independent connectivity contexts in this project:

1. **Build-time (Packer).** Packer's communicator connects to ephemeral EC2 instances during image builds. Ansible
   runs inside Packer as a provisioner and inherits Packer's transport.
2. **Day-2 (AAP).** Ansible Automation Platform connects to long-lived production Windows instances for patching,
   compliance rescans, and configuration drift remediation. FIPS compliance of the transport matters most here.

## Architecture

The image-build pipeline has two layers of Ansible, and only one of them touches Windows:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  AAP / CLI                                                              │
│  ansible-playbook build_windows.yml                                     │
│    hosts: method_packer  (phantom inventory -- no real connection)       │
│    role: windows_image_build                                            │
│      → templates Packer HCL + provisioner playbooks                     │
│      → runs "packer build" on the builder host                          │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ packer build (on Linux builder EC2)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Packer  (communicator = "winrm", port 5986 HTTPS)                      │
│    launches temporary Windows EC2 instance                              │
│    connects via WinRM using bootstrap self-signed cert                  │
│                                                                         │
│    provisioner "ansible" → windows-harden.yml   (MindPoint STIG)        │
│    provisioner "ansible" → windows-scan.yml     (PowerSTIG audit)       │
│    provisioner "file"    → download scan results                        │
│    provisioner "ansible" → windows-sysprep.yml  (generalize + shutdown) │
│                                                                         │
│    snapshots EBS → registers AMI → terminates instance                  │
└─────────────────────────────────────────────────────────────────────────┘
```

The outer Ansible never connects to Windows. The inner Ansible (Packer provisioner) inherits whatever communicator
Packer provides. Switching Packer's communicator from `winrm` to `ssh` would also switch the inner Ansible transport.

Day-2 AAP management is a separate concern: AAP inventory sets `ansible_connection` independently of Packer.

## Connection Options

Three Ansible connection plugins support Windows targets:

| Feature                  | Legacy WinRM (`winrm`)      | PSRP (`psrp`)                | OpenSSH (`ssh`)              |
|--------------------------|-----------------------------|------------------------------|------------------------------|
| Ansible plugin           | `ansible.builtin.winrm`     | `ansible.builtin.psrp`       | `ansible.builtin.ssh`        |
| Network port             | 5985 (HTTP) / 5986 (HTTPS)  | 5985 (HTTP) / 5986 (HTTPS)   | 22 (TCP)                     |
| Underlying transport     | WS-Man / WinRM service      | WS-Man / WinRM service       | OpenSSH `sshd`               |
| Execution model          | New `powershell.exe` per    | Persistent Runspace Pool     | New interpreter per task     |
|                          | task                        | (threads)                    |                              |
| Task speed               | Slow                        | Fastest (~20-25% faster than | Moderate                     |
|                          |                             | WinRM)                       |                              |
| File transfer speed      | Slow (Base64 over SOAP)     | Moderate                     | Fastest (native SFTP/SCP)    |
| Python dependency (EE)   | `pywinrm`                   | `pypsrp`                     | None (uses system `ssh`      |
|                          |                             |                              | binary)                      |
| Key-based auth           | No (certificate-based       | No (certificate-based        | Yes (SSH keys)               |
|                          | possible)                   | possible)                    |                              |
| AD / Kerberos auth       | Excellent                   | Excellent                    | Via GSSAPI (pre-existing TGT |
|                          |                             |                              | only)                        |
| Password auth            | Yes (Basic, NTLM, Kerberos) | Yes (Basic, NTLM, Negotiate) | Yes (requires `sshpass`)     |
| Credential delegation    | CredSSP / Kerberos          | CredSSP / Kerberos           | GSSAPI delegation or         |
|                          | delegation                  | delegation                   | password                     |
| Pipelining               | No                          | Yes                          | Yes (ControlMaster)          |
|                          |                             | (`ansible_psrp_pipelining`)  |                              |
| Min Windows version      | Server 2012+                | Server 2012+                 | Server 2022+ (in-box OpenSSH |
|                          |                             |                              | 7.9+)                        |
| Official Ansible support | Long-standing               | Long-standing                | Since Ansible 2.18           |
| Red Hat recommendation   | Deprecate in favor of PSRP  | **Recommended for new        | Use for non-domain /         |
|                          |                             | deployments**                | key-based                    |

### WinRM Limitations (apply to both `winrm` and `psrp` plugins)

Both WinRM-based plugins share these protocol-level limitations:

- Commands run in a non-interactive session, which can prevent certain executables from running.
- Many Windows Update API calls are blocked.
- DPAPI access is blocked (affects SQL Server installers and similar).
- Credential delegation requires CredSSP or Kerberos delegation; most auth types do not delegate by default.

Mitigations: use `become` (bypasses all WinRM restrictions) or scheduled tasks for specific operations.

### SSH Limitations

- Cannot acquire a Kerberos TGT from username/password; the caller must have a valid ticket before running the
  playbook.
- Password auth requires `sshpass` on the control node and performs unconstrained delegation (same security profile
  as WinRM CredSSP).
- Default shell is `cmd.exe`; must be changed to `powershell.exe` for best compatibility and performance.
- Packer SSH note: `ssh_file_transfer_method = "sftp"` is required to work around Win32-OpenSSH MOTW (Mark of the
  Web) issues with SCP.

## FIPS 140-3 Compliance

This is the decisive factor for transport selection in FIPS-regulated environments.

### WinRM / PSRP over HTTPS

WinRM uses the Windows **SChannel** TLS provider, which is backed by the **Cryptographic Primitives Library**
(`bcryptprimitives.dll`) and the **Kernel Mode Cryptographic Primitives Library** (`CNG.sys`). These are the
FIPS 140-validated cryptographic modules in Windows. When the Windows FIPS mode registry key is enabled:

- SChannel restricts TLS to FIPS-approved algorithms and NIST curves (P-256, P-384).
- WinRM HTTPS traffic uses validated crypto end-to-end.

This means **WinRM/PSRP over HTTPS on a FIPS-enabled Windows host is using FIPS-validated cryptography**.

### OpenSSH on Windows

Windows in-box OpenSSH (Win32-OpenSSH) uses **LibreSSL** for its cryptographic operations (currently LibreSSL 4.2.0
as of Win32-OpenSSH v10.0.0.0, released October 2025). LibreSSL is **not FIPS-validated** and does not participate in
the Windows FIPS mode setting. From the Win32-OpenSSH maintainers
([PowerShell/Win32-OpenSSH#1276](https://github.com/PowerShell/Win32-OpenSSH/issues/1276)):

> Currently it does not use the Windows cryptography libraries so the global Windows FIPS compliance flags will have
> no effect on it. LibreSSL is used for cryptography which is not FIPS validated/certified.

The Win32-OpenSSH team has discussed migrating from LibreSSL to OpenSSL (which has a FIPS-validated provider), but
this has not shipped. The project status page notes that CNG support was evaluated and rejected due to the scope of
crypto interface refactoring required; LibreSSL was chosen instead.

**Bottom line:** SSH on Windows cannot be used as a FIPS-compliant Ansible transport today. You can restrict SSH
ciphers to FIPS-approved algorithms (AES-GCM, etc.), which achieves the *spirit* of FIPS, but the underlying
cryptographic module is not validated. This distinction matters for formal FIPS compliance.

## STIG Requirements

### Windows Server 2022 STIG

The 2022 STIG includes WinRM controls only -- no SSH controls:

| STIG ID  | Requirement                                           |
|----------|-------------------------------------------------------|
| V-254378 | WinRM **client** must not use Basic authentication.   |
| V-254379 | WinRM **client** must not allow unencrypted traffic.  |
| V-254380 | WinRM **client** must not use Digest authentication.  |
| V-254381 | WinRM **service** must not use Basic authentication.  |
| V-254382 | WinRM **service** must not allow unencrypted traffic. |
| V-254383 | WinRM **service** must not store RunAs credentials.   |

These controls align with using WinRM/PSRP over HTTPS with Kerberos or NTLM -- no Basic auth, no unencrypted
traffic. The current Packer bootstrap script enables Basic auth for the ephemeral build instance; this must be
locked down in the hardened AMI (MindPoint's STIG role handles this).

### Windows Server 2025 STIG

The 2025 STIG includes the same WinRM controls (V-278125 through V-278130) **plus** new OpenSSH controls:

| STIG ID  | Requirement                                                 |
|----------|-------------------------------------------------------------|
| V-285313 | Must implement OpenSSH to protect transmitted information.  |
| V-285314 | Must display the DoD banner before SSH login.               |
| V-285315 | Must require public-key authentication for SSH.             |
| V-285316 | Must not allow blank passwords for SSH.                     |
| V-285317 | Must renegotiate SSH session keys.                          |
| V-285318 | Must terminate unresponsive SSH sessions.                   |
| V-285319 | Must terminate SSH sessions after 10 minutes of inactivity. |
| V-285320 | SSH service config file must be properly secured.           |

DISA now expects OpenSSH to be **installed and hardened** on Server 2025 endpoints regardless of whether SSH is
used as the primary management transport. This means the `windows_hardening` role for Server 2025 will need to
include SSH configuration tasks even though PSRP remains the Ansible connection method.

## Recommendation

### Build-time (Packer communicator)

**Stay with `communicator = "winrm"` for now.**

- The WinRM bootstrap path is well-tested and aligns with the existing pipeline.
- FIPS compliance of the build-time transport is a lower concern: the instance is ephemeral, exists only during
  provisioning, and is destroyed after the AMI snapshot.
- The WinRM STIG controls (no Basic auth, no unencrypted traffic) apply to the **hardened AMI output**, not to the
  ephemeral build-time configuration. The Packer bootstrap script intentionally uses Basic auth + self-signed cert
  for simplicity; MindPoint's STIG role locks this down before the image is finalized.

**Future optimization:** Consider migrating to `communicator = "ssh"` with `ssh_interface = "session_manager"`. This
eliminates the need for inbound security group rules (no port 5986), provides faster file transfers via SFTP, and
removes the WinRM bootstrap script entirely. Packer's SSH+SSM support for Windows is mature. This is an operational
improvement, not a FIPS requirement.

### Day-2 management (AAP)

**Use `ansible_connection: psrp` over HTTPS (port 5986).**

- PSRP is Red Hat's recommended connection plugin for new AAP Windows deployments (AAP 2.6 guidance).
- ~20-25% faster than legacy `winrm` plugin due to persistent Runspace Pools.
- Uses the same WinRM/WS-Man transport, so it benefits from SChannel TLS with FIPS-validated crypto.
- No Windows-side changes needed vs legacy WinRM; same ports, same service, same certificates.
- Requires `pypsrp` in the execution environment (the `ee-windows` EE currently only includes `pywinrm`).

**Do not use `ansible_connection: ssh` for day-2 management in FIPS-regulated environments** until Win32-OpenSSH
ships with a FIPS-validated cryptographic library.

### Server 2025 SSH hardening (STIG-required, not Ansible transport)

For Server 2025, the STIG requires OpenSSH to be installed and hardened on the endpoint. This is an endpoint
security control, not a management transport decision. The `windows_hardening` role for Server 2025 must:

- Install and enable OpenSSH Server.
- Set `sshd_config` to require public-key authentication, disable blank passwords, disable GSSAPI if not used.
- Configure the DoD login banner.
- Set `ClientAliveInterval` / `ClientAliveCountMax` for 10-minute idle timeout.
- Secure file permissions on `sshd_config`.

These tasks apply even though Ansible connects via PSRP.

## Migration Path

If Win32-OpenSSH gains FIPS-validated crypto in the future, migrating to SSH would involve:

### Packer (build-time)

1. Replace the WinRM bootstrap script (`winrm-bootstrap.ps1.j2`) with an SSH bootstrap script that installs
   OpenSSH via `Add-WindowsCapability`, configures the Administrator's `authorized_keys`, sets the default shell
   to `powershell.exe`, and starts `sshd`.
2. Update the Packer HCL template: `communicator = "ssh"`, `ssh_username = "Administrator"`,
   `ssh_file_transfer_method = "sftp"`. Optionally add `ssh_interface = "session_manager"` to eliminate inbound
   SG rules entirely.
3. Remove the `-e ansible_winrm_server_cert_validation=ignore` extra arguments from provisioner blocks.

### AAP (day-2)

1. Change `ansible_connection` from `psrp` (or `winrm`) to `ssh` in AAP inventory group vars.
2. Set `ansible_shell_type: powershell` in group vars.
3. Distribute SSH keys to managed Windows hosts (or use Kerberos/GSSAPI with pre-existing TGTs).
4. `pywinrm` and `pypsrp` can be removed from the EE if WinRM-based connections are fully retired.

### Blockers

- **FIPS:** Win32-OpenSSH must ship with a FIPS-validated crypto library (OpenSSL FIPS Provider or CNG integration).
  Track [PowerShell/Win32-OpenSSH#1276](https://github.com/PowerShell/Win32-OpenSSH/issues/1276) and the
  [Win32-OpenSSH releases](https://github.com/PowerShell/Win32-OpenSSH/releases) for progress.
- **Kerberos:** The SSH plugin cannot acquire a Kerberos TGT from username/password. If AAP uses Kerberos auth,
  the control node must have a valid TGT before playbook execution. This may require changes to AAP credential
  configuration.

## Revisit Triggers

Re-evaluate this decision when any of the following occur:

- **Win32-OpenSSH ships with OpenSSL FIPS Provider or CNG-backed crypto.** This removes the FIPS blocker for SSH.
- **Microsoft deprecates WinRM.** Unlikely in the near term, but WinRM has received minimal feature investment
  compared to OpenSSH.
- **MindPoint / PowerSTIG collections drop WinRM support or optimize for SSH.** Currently both work over either
  transport.
- **Packer deprecates the WinRM communicator for Windows.** No indication of this, but SSH+SSM is increasingly
  the community-preferred path.
- **AAP introduces native SSH-for-Windows credential type.** Currently AAP's Windows credential type targets WinRM.

## References

- [Ansible: Managing Windows Hosts](https://docs.ansible.com/projects/ansible/latest/os_guide/intro_windows.html)
- [Ansible: Windows SSH](https://docs.ansible.com/projects/ansible/latest/os_guide/windows_ssh.html)
- [Ansible: Windows Remote Management](https://docs.ansible.com/projects/ansible/latest/os_guide/windows_winrm.html)
- [Ansible: PSRP Connection Plugin](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/psrp_connection.html)
- [Red Hat AAP 2.6: Connect Securely to Windows Hosts](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/configure-connect_securely_to_windows_hosts)
- [Microsoft: Windows FIPS 140 Validation](https://learn.microsoft.com/en-us/windows/security/security-foundations/certification/fips-140-validation)
- [Microsoft: OpenSSH for Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- [Win32-OpenSSH FIPS Discussion (Issue #1276)](https://github.com/PowerShell/Win32-OpenSSH/issues/1276)
- [Win32-OpenSSH Releases](https://github.com/PowerShell/Win32-OpenSSH/releases)
- [Packer: Amazon EBS Builder](https://developer.hashicorp.com/packer/integrations/hashicorp/amazon/latest/components/builder/ebs)
- [Packer: SSH Communicator](https://developer.hashicorp.com/packer/docs/communicators/ssh)
- Windows Server 2022 STIG: V-254378 through V-254383 (WinRM controls)
- Windows Server 2025 STIG: V-278125 through V-278130 (WinRM), V-285313 through V-285323 (OpenSSH)
