#!/bin/sh
# Partition only the two identity-checked OS disks; never select by sdX order.
set -eu
. /tmp/install-tools/root-install.conf

run_tool() {
    tool=$1
    shift
    /tmp/install-runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 \
        --library-path /tmp/install-runtime/usr/lib/x86_64-linux-gnu \
        "/tmp/install-runtime/usr/sbin/$tool" "$@"
}

find_disk() {
    expected_serial=$1
    expected_wwn=$2
    found=
    for entry in /sys/class/scsi_generic/sg*; do
        [ "$(cat "$entry/device/type")" = 0 ] || continue
        generic=/dev/${entry##*/}
        serial=$(/tmp/install-tools/sg_inq --raw -p 0x80 "$generic" |
            hexdump -v -e '1/1 "%02x"')
        echo "$serial" | grep -Eq "^0080[0-9a-f]{4}${expected_serial}(20)*$" || continue
        identifiers=$(/tmp/install-tools/sg_inq --raw -p 0x83 "$generic" |
            hexdump -v -e '1/1 "%02x"')
        case "$identifiers" in
            *01030008"$expected_wwn"*) ;;
            *) echo 'Serial matched but logical-unit WWN did not' >&2; return 1 ;;
        esac
        blocks=$(ls "$entry/device/block")
        set -- $blocks
        [ "$#" = 1 ]
        [ -z "$found" ] || return 1
        found=/dev/$1
    done
    [ -n "$found" ]
    printf '%s\n' "$found"
}

verify_disk() {
    device=$1
    expected_bytes=$2
    name=${device##*/}
    [ -b "$device" ]
    [ "$(cat "/sys/class/block/$name/size")" = "$((expected_bytes / 512))" ]
    [ "$(cat "/sys/class/block/$name/queue/logical_block_size")" = 512 ]
    [ -z "$(ls "/sys/class/block/$name/holders")" ]
    ! grep -q "$device" /proc/mounts
    for partition in /sys/class/block/"$name"/"$name"*; do
        [ ! -f "$partition/partition" ] || {
            echo "Refusing a disk with an existing partition: $device" >&2
            return 1
        }
    done
}

printf '%s  %s\n' "$RUNTIME_SHA256" /tmp/install-tools/runtime.tar.gz | sha256sum -c -
[ ! -e /sys/block/md0 ]
first=$(find_disk "$FIRST_SERIAL_HEX" "$FIRST_WWN")
second=$(find_disk "$SECOND_SERIAL_HEX" "$SECOND_WWN")
[ "$first" != "$second" ]
verify_disk "$first" "$DISK_BYTES"
verify_disk "$second" "$DISK_BYTES"
printf 'IDENTITY_GUARDS_PASSED first=%s second=%s\n' "$first" "$second"

cd /tmp/install-tools
for module in md_mod raid1 jbd2 crc16 mbcache crc32c_generic ext4; do
    wget -q -O "$module.ko" "$TRANSFER_URL/$module.ko"
done
wget -q -O modules.sha256 "$TRANSFER_URL/modules.sha256"
printf '%s  %s\n' "$MODULE_MANIFEST_SHA256" modules.sha256 | sha256sum -c -
sha256sum -c modules.sha256
for module in md_mod raid1 jbd2 crc16 mbcache crc32c_generic ext4; do
    insmod "/tmp/install-tools/$module.ko"
done

end_sector=$((PARTITION_START + PARTITION_SECTORS - 1))
for device in "$first" "$second"; do
    verify_disk "$device" "$DISK_BYTES"
    run_tool parted --script --align optimal "$device" \
        mklabel gpt unit s mkpart na-root "$PARTITION_START" "$end_sector" \
        set 1 raid on
    echo "ROOT_PARTITION_CREATED $device"
done
sleep 2
[ -b "${first}1" ]
[ -b "${second}1" ]
mkdir -p /run/mdadm
run_tool mdadm --create /dev/md0 --run --metadata=1.2 --level=1 \
    --raid-devices=2 --bitmap=internal --homehost="$NAS_HOSTNAME" \
    --name="$ARRAY_NAME" --uuid="$ARRAY_UUID" "${first}1" "${second}1"
run_tool mdadm --detail /dev/md0
MKE2FS_CONFIG=/tmp/install-runtime/etc/mke2fs.conf \
    run_tool mke2fs -t ext4 -L na-root -U "$ROOT_UUID" -m 1 -i 65536 \
        -E lazy_itable_init=0,lazy_journal_init=0 /dev/md0
mkdir -p /mnt/netapp-root
mount -t ext4 /dev/md0 /mnt/netapp-root
cat /proc/mdstat
printf 'PERSISTENT_ROOT_MOUNTED\n'
