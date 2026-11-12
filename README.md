# NetApp FAS2240-2 Linux bring-up

The 927 controller uses its existing NetApp LOADER to boot an unmodified
Debian Linux kernel. The sections below record the initial RAM-only tests
and subsequent persistent Debian installation. This remains an experimental
storage appliance. Current verified results are in
[test-results.json](test-results.json).

For current access, installed storage layout, recovery and remaining work,
start with the [927 storage handoff](docs/netapp-927-handoff.md).
Earlier sections below describe historical test stages rather than current
installation state.

## Verified on 2026-11-11

1. The FAS2240-2 has a Xeon C3528, 6 GB installed RAM, LOADER 4.3, and
   original ONTAP 8.3.1P1 boot media. The test Linux kernel sees approximately
   4 GB usable RAM. The test limits CPU startup with `maxcpus=1`.
2. LOADER accepts an ELF64 container but starts the tested entry in 32-bit
   mode. A native 64-bit entry probe failed; a 32-bit UART probe printed its
   expected marker. Returning to LOADER from the probe caused a reset.
3. The Linux wrapper runs at 0x10000000 with its own stack and GDT, prepares
   the kernel/header/initramfs, and enters the kernel's native real-mode BIOS
   setup. Linux collects the actual BIOS memory map; the wrapper does not
   invent one. Kernel execution and the interactive RAM shell were verified.
4. The stock `pm80xx` driver initializes the PMC-Sierra PM8001 (PCI 11f8:8001)
   and discovers all 24 SAS disks plus the enclosure. Initially all disks had
   unsupported 520-byte sectors. The subsequent single-disk test converted
   one disk to 512-byte sectors and verified ordinary Linux block reads;
   the subsequent parallel batch converted the other 23. All 24 now expose
   512-byte sectors and passed sampled block reads.
5. `e1000e` drives management interface eth0. The test temporarily assigned
   the existing management IP 192.168.1.154/24 after matching its MAC address.
   Its link is 100 Mbps full duplex. An HTTP fetch to the laptop succeeded,
   and laptop-to-controller ping passed 2/2. This is a management-port check;
   the separate data NICs have not been traffic-tested.
6. Only rootfs, proc, sysfs, devtmpfs and tmpfs were mounted. At initial boot,
   no attached disk was mounted or formatted. No firmware flash, saved loader environment
   update, or persistent boot-media installation was performed.

## Sources and offline rebuild

- [bootstrap.S](bootstrap.S): 32-bit entry and BIOS setup handoff in an ELF64
  container. UART 0x3f8 is taken from the device's `show devices` output.
- [bootstrap.ld](bootstrap.ld): wrapper load layout.
- [init](init): RAM-only serial shell; no installer, automatic module loading,
  storage mounting or network provisioning.
- [build.py](build.py): offline builder and memory-layout guards.
- [sources.json](sources.json): official Debian artifact URLs and recorded
  SHA256 hashes. The `stable/current` URLs can change; reject a mismatch and
  obtain the exact archived version rather than silently accepting new data.
- [test.config.json](test.config.json): customer-specific test connection and
  network intent. It is a record/template; no deployment runner consumes it
  yet. It contains no credentials.

The verified working directory is `/tmp/tf_lab/netapp-linux-test`. Preserve
it if another test is planned: binaries, prepared modules and raw logs are
there, outside Git. With that prepared directory, rebuild using:

```bash
python3 experiments/netapp-linux/build.py --work-dir /tmp/tf_lab/netapp-linux-test
```

The exported source rebuilt the exact SHA256 of the tested image. No compiler
output, kernel binary, module binary or raw console capture is tracked here.
The builder needs Python 3, GCC, GNU ld, `downloads/linux`, its matching
`downloads/SHA256SUMS`, and a prepared `root/` containing a static BusyBox.
It includes any modules already prepared under that root; it does not fetch
packages or construct a fresh module tree automatically.

For a fresh module tree, use the matching official Debian netboot initramfs
and the scsi-modules/ata-modules udebs listed in sources.json. Extract their
module trees, normalize lib versus usr/lib, decompress the selected modules,
and regenerate dependencies with `depmod -b <root> <kernel-version>`.
Retain the dependency closure of e1000e, igb, ixgbe, pm80xx, sd_mod and sg.
The tested image contains 17 modules. Never reuse host-kernel modules with
this different kernel version. Udeb subsets omit modules.builtin.modinfo;
depmod warns about that metadata, but the selected modules loaded successfully.

## Boot and recovery

Access the physical console using `ssh mrv.na_1`. Normal SSH to
`na.927.i.927.technology` does not provide this RAM shell: no SSH daemon has
been installed. Linux is left running in RAM after the successful test.

At LOADER, serve only the build directory on the laptop's LAN address and
configure the loader network transiently. Use `load -elf64 -noxsum` with the
HTTP image URL, verify the reported entry is 0x10000000, then execute `go`.
The tested driver image is about 15 MB. Do not run `flash`, `update_flash`,
`saveenv`, disk initialization or sector-format commands as part of this test.

A reboot returns to the original NetApp boot path unless AUTOBOOT is
interrupted. A console watcher must catch `Starting AUTOBOOT` and send Ctrl-C
promptly. The known PDU recovery outlet is 4; do not cycle unrelated outlets.
The original ONTAP boot reported an unfit NVRAM battery. Chris explicitly
approved its warning override for test recovery; the hardware issue remains
unresolved. No original image or rollback path has been replaced.

## Remaining work

1. Perform full surface testing and write/read verification. Sector
   conversion and sampled reads passed on all 24 disks; these checks do not
   establish full disk health.
2. Choose a persistent OS/root and configuration layout. The approximately
   2 GB original USB boot media and its rollback images require careful
   capacity planning and a backup before any writes.
3. Test data NICs, full CPU startup, usable memory, watchdog behavior,
   cooling/health monitoring, and storage error recovery.
4. Add the desired storage stack and sharing protocols only after the block
   device and persistent boot paths are established.

## Single-disk sector conversion test

Chris authorized erasing the attached disks. A subsequent test selects only
serial `74H0A0AKFUZ6`, logical-unit WWN `50000395a81bb2c4`, model
`X422_TAL13600A10`. It appeared at `/dev/sg0` during this boot; that path is
not a persistent identity. The original Micron eUSB boot media and the SCSI
enclosure are excluded. No filesystem is created by this test.

The drive reports 1,147,307,694 blocks of 520 bytes before conversion.
Its supported VPD pages do not include the supported-block-length page.
Toshiba's AL13SEB family specifications document 512–528 byte blocks;
acceptance by the NetApp firmware must be established on the selected disk.

sg3_utils 1.48 was obtained from Debian over HTTPS and checked against the
source manifest recorded in sources.json. Standalone tools were built with
`./configure --disable-shared --enable-static`, followed by
`make LDFLAGS=-all-static`, and transferred into RAM. Confirm the resulting
tools are statically linked before transfer. Normal `LDFLAGS=-static` at
configure time did not produce standalone executables through libtool.

The read-only `sg_format --dry-run --format --size=512` completed first.
Immediately before the destructive command, guards checked the sysfs device
type/model plus inquiry serial and logical-unit WWN. The selected command
was `sg_format --format --size=512 --dcrt --early --verbose /dev/sg0`.
It was accepted with exit status 0; that means the operation started, not
that it completed. `--dcrt` disables media certification, so this conversion
is not a full surface-health test. `--early` leaves formatting running in
the drive independently of the console session. Do not reboot or remove
power while the operation is in progress.

Monitor with `sg_requests --progress` and then `sg_readcap -l`. A TEST UNIT
READY query returned a pass-through setup error with exit status 0 in this
test, so its exit status alone is not reliable evidence of readiness.
Completion, Linux block-device rescan and read verification are recorded in
test-results.json. Other drives remain untouched by this single-disk test.

The format completed by 19:04:32 UTC on 2026-11-11, approximately one hour
after launch. READ CAPACITY reported 1,172,123,568 blocks of 512 bytes,
600,127,266,816 bytes total. Rescanning only this disk exposed `/dev/sda`
with the same capacity. Reads of the first 64 MiB, 1 MiB at the midpoint,
and the last 1 MiB all completed with exit status 0 and full record counts.
An untouched disk still reported 520-byte sectors. No filesystem was
created or mounted, and no persistent OS was installed.

The first automatic read-check line exceeded the serial shell's accepted
line length and stopped at a continuation prompt without executing. A
fresh connection verified that prompt, cancelled the incomplete command,
and reverified the root shell. Identity, rescan and reads then succeeded
using separate commands shorter than 600 characters. Keep future serial
commands short and wait for a completion marker and prompt between them.

References: [sg_format manual](https://manpages.debian.org/bookworm/sg3-utils/sg_format.8.en.html),
[Toshiba AL13SEB specifications](https://toshiba-semicon-storage.com/content/dam/toshiba-ss-v3/master/en/storage/product-archive/eHDD-AL13SEBxxx-Product-Overview.pdf).

## Parallel conversion of the remaining disks

Chris authorized the remaining 23 disks to be formatted in parallel on
2026-11-11. A fresh inventory confirmed 24 unique serials and logical-unit
WWNs: the previously converted disk at 512 bytes and 23 targets at 520 bytes.
The target manifest excludes the converted disk, boot media and enclosure.
All targets passed a second model/type/serial/WWN/capacity check before any
batch formats started. Workers rechecked identity immediately before their
individual destructive commands. All 23 commands were accepted and reported
format progress.

The RAM controller runs one independent worker per disk using the same
`sg_format --format --size=512 --dcrt --early --verbose` options as the
single-disk test. Each worker polls capacity and REQUEST SENSE once per
minute, with a three-hour monitoring limit. Upon completion it rechecks
identity, rescans only its disk, validates 512-byte sectors and
600,127,266,816-byte capacity, then reads 64 MiB from the beginning and
1 MiB each from the midpoint and end. Exit status and full input record
counts must pass. Failures are recorded without automatic format retries.
No filesystem creation, disk mounting or persistent OS installation occurs.

The worker scripts, target manifest and per-disk logs are in RAM under
`/tmp/format-batch*` and `/tmp/format-worker.sh`. The laptop's private working
directory holds source scripts and monitoring logs. A laptop watcher updates
the `parallel_disk_format` records in test-results.json every minute.
The controller's workers continue if the laptop console connection closes;
the laptop must remain running to keep the repository's result file current.
Live status is `cat /tmp/format-batch/*.status` from the serial RAM shell.
Do not rerun the launcher on an existing batch directory or reboot during
formatting. Completion is established by each disk's `read-verified` status,
not merely by the successful start of its format command.

The RAM image lacks `nohup`; that initial launch attempt did not start the
batch. The successful launcher used `setsid` with SIGHUP ignored and all
standard streams redirected. The temporary transfer HTTP server was stopped
after the scripts and manifest were copied.

The batch completed successfully by 20:18:35 UTC on 2026-11-11: all 23
workers reported `read-verified`, with zero failures. The final live check
confirmed `WORKERS_FINISHED` and all 24 Linux block devices at 512-byte
sectors with 1,172,123,568 sectors each. Total raw capacity is
14,403,054,403,584 bytes (14.40 TB, approximately 13.10 TiB), before any
redundancy or filesystem overhead. No disk mounts or swap were present.
The laptop watcher exited normally after recording completion. The
original boot media is intact, and Linux remains RAM-only.

## Drive health and write/read testing

Chris chose to defer OS selection until after hardware testing. The next
test stays in the RAM environment and preserves the original boot media.
[storage-test.config.json](storage-test.config.json) records the test intent;
the temporary runner uses an identity manifest derived from the verified
24-disk inventory.

Standard SCSI log pages are read with the statically built sg3_utils
`sg_logs` tool. Raw captures remain in the laptop's private working
directory and are transferred only through the authenticated serial console.
Sanitized baseline and post-test findings are stored in test-results.json.
Historic counters are retained rather than reset, allowing before/after
comparison. A healthy-looking log is not a substitute for an I/O test.

[rw-verify.c](rw-verify.c) performs the destructive sampled test. Compile with
`gcc -O2 -Wall -Wextra -Werror -static rw-verify.c -o rw-verify`.
The caller must verify the disk's type, model, serial and WWN before invoking
it. The tool requires an exclusively opened block device, the expected
capacity, writable media and 512-byte sectors. It writes 8 MiB of distinct
deterministic data near the beginning, middle and end, flushes each write,
then reads and compares the bytes through direct I/O. The optional
`--read-all` flag subsequently reads every logical block. A full read does
not write or verify a known pattern across the entire disk; the write and
comparison coverage remains 24 MiB per disk.

The parallel run uses one worker per disk. Its temporary scripts,
status files and output logs live under `/tmp/disk-io-test` on the controller.
The laptop watcher records per-disk progress in `disk_io_test`, then
collects fresh health counters and compares uncorrected-error counts with
the baseline. A final pass requires all 24 sampled write/read tests and full
reads to succeed, no increase in uncorrected error counters, and no reported
informational exception. Monitoring failures do not automatically restart
destructive tests. Keep the controller powered during testing.

The source compiled without warnings, and its non-block-device rejection
was checked against a temporary file whose contents remained unchanged.
These source/guard checks are separate from the live disk test results.

All 24 baseline queries completed successfully: no uncorrected read, write
or verify errors, no informational exceptions, and temperatures of 29–32°C.
The disks reported approximately 82,682–82,686 power-on hours and historical
non-medium errors; these counters were not cleared. The 24 sampled direct-I/O
write/read comparisons then passed. Full reads are running in parallel;
their completion and post-test health comparisons remain pending in
test-results.json. The controller workers continue without the console
connection, while the laptop must stay running for automatic result updates
and post-test health collection. The temporary tool-transfer server was
stopped after checksums were verified. Device identity manifests and health
captures were delivered through authenticated SSH, not a log-serving HTTP
endpoint.

Initial full-read progress messages appeared only at 5% intervals, leaving
the output unchanged for several minutes. Live disk counters confirmed that
reads continued. Reporting now also reads each verifier process's `rchar`
counter through `/proc/<pid>/io`, subtracts the sampled reads, and estimates
full-read progress to two decimal places. Small process-startup reads can
be included in that estimate; actual completion still requires the tool's
full-read success marker and health checks. The watcher also reports a UTC
timestamp and aggregate read rate between polls. Updating this reporting
did not restart the disk tests.

The I/O run completed successfully on 2026-11-11. All 24 sampled write/read
tests and full logical-disk reads passed. Post-test SCSI health collection
also completed for all 24 disks: uncorrected read/write/verify counters and
historical non-medium counters did not increase, informational exceptions
remained clear, and temperatures were 29–32°C. The watcher exited normally
with final status `passed`. No boot-media writes or OS installation occurred.

## Subsequent controller checks

The stock `igb` and `ixgbe` modules loaded successfully. Linux enumerates
four `igb` data ports (eth2–eth5) and two `ixgbe` data ports (eth6–eth7), in
addition to the two `e1000e` interfaces. No data-port IP addresses were
assigned; link and throughput validation remain outstanding.

All four CPU threads were present. Sequentially onlining cpu1, cpu2 and cpu3
through sysfs succeeded, leaving cpu0–cpu3 online. Topology reports two cores,
each with two threads. The boot command line still contains `maxcpus=1`;
this runtime hotplug test does not change future boot behavior. A short
checksum workload pinned to each thread produced the expected binary hash
in all 16 iterations on each of the four threads. This was an execution
check, not a sustained CPU or memory stress test.

Linux still reports 4,007,152 kB usable RAM. The firmware map identifies
0x1c0000000–0x23fffffff (2 GiB) as `Unknown E820 type`, separate from the
ordinary System RAM ranges. Its intended use has not been established; do
not force that region into normal RAM. Initially the RAM image had no
registered hwmon sensors or watchdog class. Subsequent monitoring checks
below added CPU sensors and queried the BMC without arming its watchdog.

Chris identified e1a, e1b and e0m as cabled. Management eth0 has carrier at
100 Mbps full duplex. Enabling the two ixgbe interfaces (eth6 and eth7)
succeeded, but both remain without carrier. Their mapping to e1a/e1b is
inferred from the dual-port PCI functions, not physically confirmed. The
driver detects SFP modules and reports no explicit unsupported-optics error.
No data-port addresses were assigned. Far-end switch/port details are needed
to investigate the missing links.

The requested peer, 192.168.1.150, is confirmed as ge-0/0/0.0 on the 927
SRX550 running Junos 12.1R5.5. Ping from the controller's management interface
passed 3/3. A TCP connection to iperf3 port 5201 timed out, so throughput
testing against that address is not available as-is. Management ping does
not validate either data link or establish storage-network throughput.

Chris identified the data-cable far ends as the 927 EX ports 0/2/0 and
0/2/1. On this EX the interface names are `xe-0/2/0` and `xe-0/2/1`, not
`et-...`. Both report administratively down, and their live configuration
contains `disable`. The same intent is present in
`config/927/ex/v.config.json` with `ifdisable: true` for each interface.
This is an identified blocker to bringing up the data links. No switch
configuration was changed during diagnosis; any enablement must originate
in JSON and go through the Terraform plan/apply workflow.

Chris subsequently requested enabling the two ports in JSON and applying
only if the plan contained just those changes. Both `ifdisable` flags were
set to false. The ignored provider JSON's obsolete `bastion` alias was
corrected to `bastion.927.i.927.technology` so the standard wrapper could
connect. The full EX plan reported 0 additions, 2 in-place changes and
0 destroys; each device change only removes the interface's `disable` flag.
It also removes two obsolete inventory outputs and reshapes four root
outputs. Those state-output changes are unrelated to enabling the ports,
so apply was not run under the user's initial condition. At that point the
live EX ports remained disabled pending approval of the output changes.

Chris then explicitly approved apply. A refreshed saved plan was checked
for exactly the two interface-disable removals and the reviewed output
migrations. An additional security-zone output entry had identical JSON
values before and after; it represented empty-collection type normalization.
The reviewed saved plan applied successfully: 0 additions, 2 changes and
0 destroys. The standard junos-files capture follow-up also succeeded.
Live verification now shows both EX ports up/up and both NetApp ixgbe
interfaces with carrier at 10,000 Mbps full duplex. No data-port IP address
or VLAN configuration was added, and throughput testing remains outstanding.

## Temperature, fan and watchdog checks

Chris subsequently accepted network throughput by assumption. No measured
throughput result is claimed; the data-link negotiation checks remain the
available network evidence.

The exact running-kernel Debian image package was downloaded over HTTPS and
verified against the SHA256 in Debian's package metadata. The source URL and
checksum are recorded in sources.json. Only `coretemp`, `ipmi_msghandler`,
`ipmi_si` and `ipmi_devintf` were extracted and loaded into RAM. Firmware
already advertised `dmi-ipmi-si.0`; no forced I2C addresses or blind SMBus
sensor probes were used. These additions do not change the original tested
boot image or install anything on persistent media.

1. `coretemp` exposes both physical cores. Initial readings were 42°C and
   40°C, with driver-reported critical thresholds of 101°C and clear critical
   alarms. A bounded 40-second workload pinned to all four CPU threads peaked
   at 48°C and 46°C. The test had an 85°C stop guard, completed normally and
   removed its workers. This is a brief load check, not a sustained burn-in.
2. Standard read-only SES queries against the identified DS224IOM6E enclosure
   report all four fans OK at 3020/3000/3000/3000 RPM, before and after load.
   Seven temperature sensors are OK at 23–39°C. Sensor 7 is `Unknown` with a
   raw zero reading; zero is not treated as a valid measured temperature.
   Aggregate SES descriptors report `Unsupported`; their zero fan fields
   must not be mistaken for stopped individual fans.
3. The BMC IPMI interface responds. Intake/exhaust temperatures were 36/41°C
   and battery temperature 31°C. CPU/memory-hot and thermal-trip flags were
   deasserted. The CPU temperature-margin sensor is a margin, not a negative
   absolute CPU temperature. IANA-name lookup warnings from the temporary
   minimal runtime did not prevent successful numeric BMC queries.
4. `ipmitool -I open mc watchdog get` reports the timer stopped, action none,
   BIOS FRB2 use, zero countdown and no expiration flags. The `ipmi_watchdog` module
   was not loaded and `/dev/watchdog` was not opened; no timer set/reset
   command was issued.
   Watchdog-triggered reset behavior remains untested and should be evaluated
   with a suitable persistent boot/recovery setup.
5. PSU1 is OK. PSU2 is present but reports critical/off with AC and DC failure;
   the BMC independently asserts `PSU2_Fault`. Two enclosure voltage sensors
   report 0 V and `Unrecoverable`; the other two report 5.07 V and 12.30 V OK.
   Chris confirmed PSU2 is not connected to live AC. This explains its
   power-input alarm; a PSU hardware failure has not been established.
   Overall enclosure critical/unrecoverable flags remain set.
   No power-supply redundancy pass is claimed, and the earlier ONTAP battery
   fitness warning has not been resolved by reading present sensor values.

Debian's checksum-verified ipmitool 1.8.19-9 binary and libfreeipmi runtime
were used with temporary copies of the laptop's loader/libraries. No host
packages were installed. The temporary runtime bundle hash is recorded in
sources.json; binaries and raw console captures stay outside Git. Only tools
and modules were served by the temporary transfer HTTP server, which has now
been stopped. Sensor output returned through authenticated SSH serial access.
Fan-control settings were not changed. Linux and all added tooling remain
RAM-only, with the original ONTAP boot media intact.

References: [coretemp driver](https://docs.kernel.org/hwmon/coretemp.html),
[Linux IPMI interface](https://docs.kernel.org/driver-api/ipmi.html),
[watchdog API](https://docs.kernel.org/watchdog/watchdog-api.html).

References: [Linux boot protocol](https://www.kernel.org/doc/html/latest/arch/x86/boot.html),
[Debian boot documentation](https://www.debian.org/releases/stable/amd64/ch05s01.en.html),
[Linux PM8001 driver](https://github.com/torvalds/linux/tree/master/drivers/scsi/pm8001).

## Internal eUSB boot preparation

Chris authorized backing up the original eUSB to the laptop at
`/tmp/tf_lab/netapp-eusb-backup/` and preparing Linux boot on that device.
The intent and identity guards are recorded in [boot.config.json](boot.config.json).
This later authorization permits boot-file preparation beyond the earlier RAM-only test.

The original Micron eUSB serial `B8F0022700200059` exposes 3,964,928
512-byte sectors (2,030,043,136 bytes). Its FAT16 partition starts at
sector 252 and has 3,951,738 sectors. Initial read-only directory inspection
reported about 1.2 GB free, sufficient to add the verified 15 MB ELF wrapper
without deleting the existing ONTAP files. Linux USB host and mass-storage
drivers were loaded in RAM; the eUSB enumerated at 12 Mbps after high-speed
enumeration timed out. No additional external USB storage was detected.

A full raw backup is being streamed to a private, untracked laptop directory.
The receiver checks the source IP and exact byte count and hashes received
bytes; the controller hashes the same source stream independently. Boot-media
writes must wait for backup completion, matching checksums, and filesystem
inspection. The backup can contain credentials and proprietary images: do not
commit it, publish it, or serve it through the boot-image HTTP directory.

The first persistent boot stage will still use the existing RAM-only Linux
root filesystem. It does not install Debian on the SAS disks. Manual loading
from eUSB and automatic startup remain unverified until recorded otherwise.
Preserving ONTAP boot files preserves its boot path, not the erased SAS data.

The filesystem also mounted successfully in Linux with read-only, nodev,
nosuid and noexec options, explicitly selecting `iocharset=iso8859-1` and
`codepage=437`. The initial default charset was unavailable in this minimal
RAM environment; selecting the loaded charset resolved that mount error.
`df` reported 1,179,264 KiB free. It was unmounted after inspection.
No boot-file writes or loader-setting changes have occurred.

For continuation, the laptop receiver is `receive.py` in the approved private
backup directory. It creates `backup.json` only after the exact byte count
is received and flushed. While running, `progress.json` reports byte count.
On the controller, `/tmp/eusb-backup/run.log`, `dd.exit`, and `stream.sha256`
record completion and the independent source-stream checksum. Require the
full image, `dd.exit` equal to zero, and matching hashes before any eUSB writes.
Do not reboot or disconnect power while this backup is running.

The complete 2,030,043,136-byte backup subsequently finished with source
copy exit status zero. The source-stream SHA256 and a fresh hash of the saved
image both match `eaee9f1367f3031d031feb787b59e958ecdbd2dc2fdec43ee1236ab05f6681aa`.
The original backup remains unchanged. Offline checking found the two FATs
differ only at entry 1's clean-shutdown bit; allocation entries match.
Normalizing that bit on a separate staging partition image, adding the ELF,
and checking it again produced a clean filesystem and exact file round-trip hash.

`/LINUX.ELF` (14,798,696 bytes) was then added to the existing eUSB filesystem.
All original files were retained. The filesystem was flushed, unmounted,
remounted read-only and the new file's SHA256 matched the tested image.
A guarded reboot captured the original LOADER environment privately. Manual
`load -elf64 -noxsum fat://boot0/LINUX.ELF` reported entry `0x10000000`;
`go` reached the Linux RAM shell successfully. This verifies local eUSB boot
without requiring the laptop HTTP server for the kernel/initramfs.

LOADER rejected changing `GX_PRIMARY_KERNEL_URL` because it is read-only.
The initial test script did not stop on that error and invoked the unchanged
ONTAP primary boot command. The controller became unresponsive during that
boot attempt; only `na_1` was cycled through the existing lab stop/start
functions, and the serial watcher recovered the LOADER prompt. Future boot
configuration tests must check command results before invoking the boot path.

[add-loader-checksum.py](add-loader-checksum.py) adds the observed integrity
note to the existing ELF wrapper. The format was checked against the original
backed-up kernel: its embedded MD5 matches the whole file with the 16 digest
bytes zeroed. The helper adds a `Network Appliance` SHT_NOTE, computes that
integrity value, and asserts the execution entry and all loadable segment
contents and memory geometry remain unchanged. This is an integrity checksum,
not an authentication mechanism. Two independent builds produced SHA256
`ef3d5994e7ce0ac1f9df3812086f6dd31edf29d690bf8703df13e501cebede6f`.

The normal `boot -elf64` command, without `-noxsum`, accepted this image over
HTTP and reached Linux. To use the fixed primary boot path, installation
retains the original kernel as `x86_64/freebsd/image1/kernel.ontap` and places
the checksum-enabled wrapper at `x86_64/freebsd/image1/kernel`. The original
kernel's SHA256 is verified before changing that path. The image2 kernel,
platform modules, firmware images, original raw backup and LOADER defaults
remain available. The root `/LINUX.ELF` manual-boot copy also remains.

The guarded primary installation completed: the original kernel matched its
backup hash, the new wrapper matched its build hash, the original was renamed
to `kernel.ontap`, and the new wrapper was installed as `kernel`. After sync,
unmount and read-only remount, the installed primary file matched SHA256
`ef3d5994e7ce0ac1f9df3812086f6dd31edf29d690bf8703df13e501cebede6f`.

A warm `reboot -f` stalled after the Linux restart message, before any BIOS
or LOADER output, for the 180-second observation window. This is unresolved
and must not be described as a successful warm-reboot test. A subsequent
controller-only cold start through `lab.stop.na_1` / `lab.start.na_1` passed:
AUTOBOOT loaded `X86_64/freebsd/image1/kernel` at entry `0x10000000`, started
Linux, and reached the RAM shell without a network boot or console interrupt.
The primary URL and AUTOBOOT selection were left at their existing values.

This completes persistent eUSB kernel/initramfs boot, not a persistent Debian
root installation. The shell and runtime configuration are still in RAM;
there is no installed SSH daemon, storage pool or NAS service. Installing the
persistent root filesystem and configuring startup services remains separate
work. The original ONTAP kernel and full eUSB backup do not restore erased SAS data.

After the successful cold boot, the test runtime was restored and checked:
all four CPU threads online, all 24 SAS disks visible, management at
192.168.1.154/24 with 100 Mbps carrier, both data links at 10 Gbps, core
temperatures 40/37 degrees C, and `/dev/ipmi0` present. Laptop ping passed
2/2. No storage filesystem was mounted. The temporary image/module HTTP
server was stopped after restoring the test runtime. These runtime settings
are not yet an automatic persistent OS configuration.

## Persistent Debian and storage networking, 2026-11-12 UTC

Customer intent is in
[config/927/na/v.config.json](config/927/na/v.config.json).
The bootstrap utilities consume this JSON; there is no Terraform OS
provisioning stack for this controller yet. The EX remains managed through
its existing JSON and Junos Terraform stack.

Two explicitly identified SAS disks were reserved for the operating system:
serials `74H0A0AKFUZ6` and `74I0A02PFUZ6`. Each has one 64 GiB GPT partition;
their remaining capacity stays reserved and unused. These partitions form
`/dev/md0`, a metadata-1.2 RAID1 with an internal write-intent bitmap and an
ext4 root. Its array and filesystem UUIDs are recorded in the customer JSON.
The mirror synchronized successfully with both members present. The other
22 disks were excluded from root installation by serial and logical-unit
WWN checks, not by assumed `/dev/sdX` names.

[install-root.sh](install-root.sh) guards geometry, identity, mounts and
holders before creating the root partitions. The Debian 13 `trixie` base
was prepared with a foreign debootstrap stage and completed on the controller.
Debian Release signatures and package hashes were verified against the
[published Debian archive keys](https://ftp-master.debian.org/keys.html).
The installation follows the
[Debian bootstrap procedure](https://www.debian.org/releases/trixie/amd64/apds03.en.html).
The chroot needs `/dev`, devpts, proc and sysfs mounted; package installation
must have detached standard input or run in the serial shell foreground to
avoid a stopped terminal-input job. Invoke chroot validation programs by
absolute path when BusyBox standalone applet lookup could intercept them.

[configure-persistent.py](configure-persistent.py) renders hostname, UUID
mounts, RAID monitoring, management networking, LACP/VLAN networking, SSH
public-key access, sudo, logging limits and CPU startup configuration. The
administrator is `admin`, using the existing configured public key; passwords
and root SSH login are disabled. SSH host private keys were generated on the
controller and were not copied into the transfer server or Git. The new host
public key was obtained over the trusted serial console before SSH testing.
Root has a 2 GiB swapfile. The RTC was corrected to UTC and NTP synchronized.
An initial CPU online attempt failed early in systemd startup; a later retry
brought all four threads online. The startup helper now makes bounded retries.
RAID monitor events go to the system journal rather than an undefined email
address. These local journal alerts do not provide external notification.

[prepare-persistent-boot.py](prepare-persistent-boot.py) and
[init-persistent](init-persistent) build an initramfs that assembles only the
configured root UUID, verifies the ext4 UUID, checks the filesystem and hands
off to installed Debian. Failure enters a serial recovery shell without
initializing disks. The persistent ELF passed manual HTTP boot with normal
LOADER checksum checking. Debian reached login, authenticated SSH worked,
root was mounted read/write from `/dev/md0`, and swap was active. After the
startup fixes, no systemd services were failed and all four threads were online.

The tested checksum-enabled persistent image has SHA256
`bcf985043c69d2581a454695910584819502243acd99db2cd74c3bb4f5efc8ed`.
It replaced the eUSB primary only after the manual test. The previous
checksum-enabled RAM primary remains at `image1/kernel.ram`, the original
ONTAP primary remains at `image1/kernel.ontap`, and `/LINUX.ELF` remains the
manual RAM recovery image. Copy hashes were checked after sync, unmount and
read-only remount. The full raw eUSB backup remains unchanged. The earlier
warm-reboot stall remains unresolved; a clean Debian poweroff followed by a
controller-only cold start is the current recovery/test procedure.

The unattended persistent boot test passed after clean Debian poweroff and
a controller-only cold start. The temporary image server was stopped before
the test. No console interrupt or network boot was used. The saved root
persistence marker survived; the root mirror had both members, swap was
active, four CPU threads came online automatically, no services failed, and
the storage gateway answered 3/3 pings. The existing SSH alias
`na.927.i.927.technology` works. Its old ONTAP known-host entry was replaced
with the Debian public key verified through the trusted serial console.

The EX JSON enables unused `ae0` as a LACP active/fast trunk carrying only
VLAN 197 (`WHT_MGMT-STORAGE`) and attaches `xe-0/2/0` and `xe-0/2/1`.
The first apply committed the member ports and aggregate but failed its RSTP
entry because that commit ran before Ethernet switching existed on `ae0`.
RSTP now consumes managed interface names through the physical module's
`map` output, establishing resource creation order. Module-level `depends_on`
cannot be used with this legacy module's internal provider configuration.
The reviewed retry added only the missing RSTP entry and succeeded; the
follow-up non-refreshing plan against newly written state was clean.
Live EX inspection showed both links collecting/distributing with `ae0.0`
up for Ethernet switching. Linux uses `bond0` with both 10 GbE members and
`storage197` at `10.1.252.10/24`. Its gateway `10.1.252.1` answered 3/3 pings.
Management stays on `e0m`, `192.168.1.154/24`. No throughput result is claimed.

Chris selected one 22-disk RAID6 array and requested all resulting capacity
remain unallocated for now. Client subnets and iSCSI initiators are undecided.
[create-data-array.py](create-data-array.py) defaults to a read-only preview;
its explicit `--apply` initializes only JSON-listed empty disks after serial,
WWN, capacity, sector size, partition, holder and signature checks. It refuses
to rerun against an existing array or volume group. The intended layering is
RAID6 → LVM volume group → separate future SMB/NFS filesystems and iSCSI LUNs.
See the Debian [mdadm](https://manpages.debian.org/trixie/mdadm/mdadm.8.en.html)
and [vgcreate](https://manpages.debian.org/trixie/lvm2/vgcreate.8.en.html) manuals.
SMB, NFS and iSCSI packages are installed, but servers/targets remain masked
and no shares, targets or logical volumes have been defined.

The selected RAID6 was subsequently created as `/dev/md1`, array UUID
`fc1f8d3d:cb9f1f61:625830d0:458262df`, with all 22 members active and no
failed members. Initial synchronization is running in the background; its
completion has not yet been verified. The `nas` LVM volume group has
11,999,819,857,920 bytes, all free, and zero logical volumes. Both array UUIDs
are persisted in rendered `mdadm.conf`; monitoring is active and the
installed Debian initramfs metadata was updated. The boot wrapper still
assembles only root before handing off to Debian. Final listener inspection
showed SSH only, with no SMB/NFS/iSCSI listeners. Do not rerun either disk
initializer against the installed arrays.

## Repository integration

This repository is included by `927technology/tf_lab` as the submodule
`experiments/netapp-linux`. Its customer JSON lives here under `config/927/na/`;
tf_lab links its original customer configuration path to that file. EX
configuration and Junos Terraform modules remain owned by tf_lab. The handoff
in this repository records their validated integration. Binaries, raw captures,
backup images, runtime environments and credentials are not published here.

## Configuration contract

Put customer intent in JSON and keep bootstrap code generic. Do not run disk
initializers against installed arrays. Infrastructure deployment requires a
reviewed plan and explicit approval. Follow the tf_lab coding standards for
related Terraform work, including its four module outputs and prohibition on
locals. This repository does not authorize communication between agents outside
the established main-branch, human-approved PR workflow.
