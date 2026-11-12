"""Render persistent Debian configuration from customer/environment JSON."""
import argparse
from pathlib import Path
import shlex


def render(config, output):
    import json
    data = json.loads(config.read_text())['linux']
    root = data['os']['root']
    management = data['management']
    storage = data['storage']
    admin = data['administrator']

    def write(name, text, mode=0o644):
        path = output / name.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)

    write('/etc/hostname', data['hostname'] + '\n')
    write('/etc/hosts', '127.0.0.1 localhost\n127.0.1.1 '
          + data['hostname'] + '.' + data['customer'] + '.i.927.technology '
          + data['hostname'] + '\n::1 localhost ip6-localhost ip6-loopback\n')
    write('/etc/fstab', 'UUID=' + root['filesystem_uuid']
          + ' / ext4 defaults,noatime,errors=remount-ro 0 1\n'
          + '/swapfile none swap sw 0 0\n')
    arrays = 'ARRAY ' + root['array'] + ' UUID=' + root['array_uuid'] + '\n'
    layout = storage.get('data_layout') or {}
    if layout.get('array_uuid'):
        arrays += 'ARRAY ' + layout['array'] + ' UUID=' + layout['array_uuid'] + '\n'
    write('/etc/mdadm/mdadm.conf', 'HOMEHOST <system>\nDEVICE partitions\n'
          + 'PROGRAM /usr/local/sbin/netapp-md-event\n' + arrays)
    write('/usr/local/sbin/netapp-md-event',
          '#!/bin/sh\nexec logger -p daemon.err -t mdadm -- "$@"\n', 0o755)
    write('/etc/apt/sources.list',
          'deb https://deb.debian.org/debian trixie main\n'
          'deb https://deb.debian.org/debian trixie-updates main\n'
          'deb https://security.debian.org/debian-security trixie-security main\n')
    write('/etc/default/locale', 'LANG=C.UTF-8\n')
    write('/etc/modules-load.d/netapp.conf',
          'bonding\ncoretemp\nipmi_msghandler\nipmi_si\nipmi_devintf\nrtc_cmos\n')
    write('/etc/ssh/sshd_config.d/10-key-only.conf',
          'PasswordAuthentication no\nKbdInteractiveAuthentication no\n'
          'PermitRootLogin no\nPubkeyAuthentication yes\n')
    public_key = Path(admin['authorized_key_file']).expanduser().read_text().strip()
    if '\n' in public_key or not public_key.startswith(('ssh-', 'ecdsa-')):
        raise ValueError('Expected one SSH public key')
    write('/home/' + admin['name'] + '/.ssh/authorized_keys', public_key + '\n', 0o600)
    write('/etc/sudoers.d/90-netapp-admin',
          admin['name'] + ' ALL=(ALL:ALL) NOPASSWD: ALL\n', 0o440)
    write('/etc/systemd/journald.conf.d/10-storage-limits.conf',
          '[Journal]\nRuntimeMaxUse=32M\nSystemMaxUse=128M\nSystemKeepFree=512M\n')

    def link(name, mac):
        write('/etc/systemd/network/10-' + name + '.link',
              '[Match]\nMACAddress=' + mac + '\n[Link]\nName=' + name + '\n')

    link(management['interface'], management['mac'])
    write('/etc/systemd/network/20-management.network',
          '[Match]\nName=' + management['interface'] + '\n[Network]\nAddress='
          + management['address'] + '\nGateway=' + management['gateway']
          + '\nDNS=' + ' '.join(management['dns'])
          + '\nIPv6AcceptRA=no\nLinkLocalAddressing=no\n')
    bond = storage['bond']
    write('/etc/systemd/network/20-storage-bond.netdev',
          '[NetDev]\nName=' + bond['interface'] + '\nKind=bond\n[Bond]\nMode='
          + bond['mode'] + '\nMIIMonitorSec=100ms\nLACPTransmitRate='
          + bond['lacp_rate'] + '\nTransmitHashPolicy=' + bond['transmit_hash_policy'] + '\n')
    for member in bond['members']:
        link(member['interface'], member['mac'])
        write('/etc/systemd/network/30-' + member['interface'] + '.network',
              '[Match]\nName=' + member['interface']
              + '\n[Link]\nRequiredForOnline=no\n[Network]\nBond='
              + bond['interface'] + '\nIPv6AcceptRA=no\nLinkLocalAddressing=no\n')
    network = storage['network']
    write('/etc/systemd/network/40-storage-bond.network',
          '[Match]\nName=' + bond['interface']
          + '\n[Link]\nRequiredForOnline=no\n[Network]\nVLAN='
          + network['interface'] + '\nLinkLocalAddressing=no\n')
    write('/etc/systemd/network/40-storage-vlan.netdev',
          '[NetDev]\nName=' + network['interface'] + '\nKind=vlan\n[VLAN]\nId='
          + str(network['vlan_id']) + '\n')
    write('/etc/systemd/network/50-storage-vlan.network',
          '[Match]\nName=' + network['interface']
          + '\n[Link]\nRequiredForOnline=no\n[Network]\nAddress='
          + network['address'] + '\nIPv6AcceptRA=no\nLinkLocalAddressing=no\n')
    write('/usr/local/sbin/netapp-online-cpus',
          '#!/bin/sh\nset -eu\nfor cpu in /sys/devices/system/cpu/cpu*/online; do\n'
          '    [ -f "$cpu" ] || continue\n'
          '    for attempt in 1 2 3; do\n'
          '        [ "$(cat "$cpu")" != 1 ] || break\n'
          '        if echo 1 > "$cpu"; then break; fi\n'
          '        sleep 2\n'
          '    done\n'
          '    [ "$(cat "$cpu")" = 1 ]\ndone\n', 0o755)
    write('/etc/systemd/system/netapp-online-cpus.service',
          '[Unit]\nDescription=Online the tested NetApp CPU threads\n'
          'After=systemd-modules-load.service\nBefore=network-pre.target\n'
          '[Service]\nType=oneshot\nExecStart=/usr/local/sbin/netapp-online-cpus\n'
          'RemainAfterExit=yes\n[Install]\nWantedBy=multi-user.target\n')
    write('/root/netapp-provision.env',
          'NAS_ADMIN=' + shlex.quote(admin['name']) + '\n'
          + 'NAS_TIMEZONE=' + shlex.quote(data['os']['timezone']) + '\n'
          + 'NAS_SWAP_BYTES=' + str(data['os']['swap_bytes']) + '\n', 0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    render(args.config, args.output)
