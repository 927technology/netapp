# 927 NetApp storage handoff

Prepared November 11, 2026 (America/Chicago), from the completed installation
and validation session. Some underlying captures are dated November 12 UTC.
This document records the last verified state; RAID synchronization has not
been checked again for this documentation update. It is intended for internal
sharing and contains management addresses, but no credentials or raw captures.

## Installed system

| Item | Last verified state |
| --- | --- |
| Customer / device | 927 / NetApp FAS2240-2, hostname `na` |
| OS | Debian 13 `trixie`, amd64 |
| Kernel | `6.12.107+deb13-amd64`, held at the tested version |
| CPU / memory | Four CPU threads online; approximately 4 GiB usable RAM |
| Boot | Existing NetApp LOADER 4.3, internal Micron 2 GB eUSB |
| Root | `/dev/md0`, two-disk RAID1, ext4, approximately 64 GiB |
| Swap | 2 GiB swapfile on root |
| Data | `/dev/md1`, one 22-disk RAID6, all 22 members active, zero failed |
| Allocation | LVM group `nas`: 11,999,819,857,920 bytes, entirely free; zero logical volumes |
| Services | SSH available; SMB, NFS and iSCSI installed but disabled/unconfigured |
| Clock | UTC RTC and synchronized NTP |

The root mirror completed synchronization. Data RAID6 initial synchronization
was still running at the last check (approximately 1%); completion is unverified.
Chris requested all data capacity remain unallocated. Client networks and
iSCSI initiator IQNs are undecided. No data filesystem, share or LUN exists.
Future SMB/NFS filesystems and iSCSI volumes can have separate allocations
from the same LVM group.

## Access and networking

```sh
ssh na.927.i.927.technology
```

This is an SSH configuration alias, not a DNS record. The existing workstation
entry connects as `admin` using its configured private key. SSH key
authentication was verified; password authentication and root SSH login are
disabled. The Debian host public key was obtained through the trusted serial
console before replacing the old ONTAP known-host entry. Private keys are not
included in this handoff. Other operators need their own authorized access.

| Purpose | Configuration |
| --- | --- |
| Management | `e0m`, `192.168.1.154/24`, gateway/DNS `192.168.1.1`; observed 100 Mbps carrier |
| Storage members | `e1a` and `e1b`, each 10 GbE |
| Linux aggregate | `bond0`, 802.3ad, active/fast LACP, transmit hash `layer3+4` |
| Storage VLAN | `storage197`, VLAN 197, `10.1.252.10/24` |
| Storage gateway | `10.1.252.1`; three of three source-bound pings passed |
| EX aggregate | `ae0`, trunk carrying `WHT_MGMT-STORAGE` only |
| EX members | `xe-0/2/0` and `xe-0/2/1`; both collecting/distributing |
| Serial console | Existing SSH alias `mrv.na_1` |

LACP convergence and gateway reachability were verified. Aggregate throughput,
single-flow throughput and NAS workload performance have not been benchmarked.

## Configuration and evidence

1. [Controller intent](../config/927/na/v.config.json): disk serials/WWNs,
   array UUIDs, boot settings, addresses, LACP and deferred allocations.
2. [EX intent](https://github.com/927technology/tf_lab/blob/main/config/927/ex/v.config.json): aggregate, member ports, VLAN
   and RSTP settings, deployed with the existing Junos Terraform wrappers.
3. [Bring-up and installation record](../README.md):
   hardware tests, image construction, verification and installation details.
4. [Recorded test results](../test-results.json) and
   [boot profile](../boot.config.json): sanitized
   results, image hashes and recovery file identities.

Controller bootstrap scripts consume JSON, but the controller OS is not yet
managed by a Terraform provisioning stack. Disk initializers are one-time
tools; do not rerun them against the installed arrays. The data initializer's
refusal to rerun against the existing array was verified.

The EX deployment initially failed only its RSTP resource because Terraform
attempted that commit before aggregate Ethernet switching existed. The ports
and aggregate had committed successfully. RSTP now consumes managed interface
names through the physical module's `map` output, establishing ordering. The
retry added only the missing RSTP entry and succeeded. The final plan was clean
with `refresh=false` against newly written state; live EX inspection separately
verified the aggregate and both LACP members. Terraform validation, formatting,
Python compilation and whitespace checks passed.

## Boot and recovery

Unattended cold boot passed with the temporary image server stopped and no
console intervention. Debian mounted mirrored root read/write, retained a
saved persistence marker, enabled swap, brought all four CPU threads online
and had no failed systemd services. The normal customer SSH alias worked.

| eUSB file | Purpose |
| --- | --- |
| `/x86_64/freebsd/image1/kernel` | Tested persistent Debian boot wrapper |
| `/x86_64/freebsd/image1/kernel.ram` | Preserved checksum-enabled RAM boot wrapper |
| `/LINUX.ELF` | Previously tested manual RAM recovery image |
| `/x86_64/freebsd/image1/kernel.ontap` | Preserved original ONTAP primary |

Warm `reboot -f` previously stalled before BIOS/LOADER output and remains
unresolved. The validated procedure is clean Debian poweroff followed by a
controller-only cold start using the existing `lab.stop.na_1` and
`lab.start.na_1` functions. Wait for clean shutdown before removing power.
Do not cycle other lab devices for controller recovery.

If automatic boot fails, use `mrv.na_1` and interrupt AUTOBOOT to reach
`LOADER-A>`. The previously verified manual RAM recovery commands are:

```text
load -elf64 -noxsum fat://boot0/LINUX.ELF
go
```

This starts the RAM recovery environment, not the installed NAS services.
Do not initialize or format disks during recovery. The original ONTAP kernel
and eUSB backup do not restore erased SAS data.

A complete verified raw eUSB backup remains outside Git at
`/tmp/tf_lab/netapp-eusb-backup/micron-B8F0022700200059.img` on the preparation
workstation. `/tmp` is not durable backup storage; arrange a protected durable
copy before discarding the preparation environment. No backup image or private
operational log is bundled with this document.

## Remaining work

1. Verify RAID6 initial synchronization completes with all 22 members and no
   errors. Check `cat /proc/mdstat` and `sudo mdadm --detail /dev/md1`.
2. Keep capacity unallocated and shares/targets disabled until Chris supplies
   allocation sizes, client subnets, iSCSI initiators and access requirements.
3. Benchmark storage and network performance after synchronization. No service
   performance or failover result has been established.
4. Investigate warm reboot and establish a repeatable kernel/boot-image update
   procedure before changing the pinned kernel. Updating Debian's normal
   initramfs alone does not replace the custom eUSB boot wrapper.
5. Arrange durable recovery backups and external RAID alerts. Current RAID
   monitor notifications go only to the local system journal.
6. Resolve or accept the previously observed hardware limitations: PSU 2 is
   intentionally unplugged, power redundancy is untested, and the legacy
   NVRAM battery is unfit. The Linux storage design does not rely on that
   battery-backed NVRAM.
