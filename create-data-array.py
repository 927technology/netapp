"""Plan or initialize the explicitly configured, empty NAS data disks."""
import argparse
import json
from pathlib import Path
import subprocess


def run(*command):
    return subprocess.check_output(command, text=True)


def plan(config):
    data = json.loads(config.read_text())['linux']
    storage = data['storage']
    layout = storage['data_layout']
    expected = storage['data_disks']
    system = {disk['wwn'] for disk in data['os']['system_disks']}
    if (
        layout['level'] != 'raid6' or
        layout['member_layout'] != 'whole-disk' or
        len(expected) != storage['data_disk_count'] or
        len({disk['wwn'] for disk in expected}) != len(expected) or
        any(disk['wwn'] in system for disk in expected)
    ):
        raise ValueError('Invalid or overlapping data disk configuration')
    if Path(layout['array']).exists():
        raise ValueError('Array already exists; this initializer must not be rerun')
    if json.loads(run('vgs', '--reportformat', 'json'))['report'][0]['vg']:
        raise ValueError('Existing volume groups require manual review')
    inventory = json.loads(run(
        'lsblk', '--json', '--bytes', '--output',
        'NAME,PATH,TYPE,SIZE,LOG-SEC,SERIAL,WWN,MOUNTPOINTS'
    ))['blockdevices']
    members = []
    for disk in expected:
        matches = [
            item for item in inventory
            if (
                item['type'] == 'disk' and
                (item.get('wwn') or '').removeprefix('0x') == disk['wwn'] and
                item.get('serial') == disk['serial']
            )
        ]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous disk: ' + disk['serial'])
        item = matches[0]
        if (
            item['size'] != disk['capacity_bytes'] or
            item['log-sec'] != 512 or
            item.get('children') or
            any(item.get('mountpoints') or []) or
            any((Path('/sys/class/block') / item['name'] / 'holders').iterdir()) or
            json.loads(run('wipefs', '--no-act', '--json', item['path']))['signatures']
        ):
            raise ValueError('Disk geometry or empty-device check failed: ' + item['path'])
        members.append(item['path'])
    commands = [
        ['mdadm', '--create', layout['array'], '--metadata=' + layout['metadata'],
         '--name=' + layout['name'], '--homehost=' + data['hostname'],
         '--level=' + layout['level'], '--raid-devices=' + str(len(members)),
         '--chunk=' + str(layout['chunk_kib']), '--bitmap=internal', '--run', *members],
        ['pvcreate', layout['array']],
        ['vgcreate', layout['volume_group'], layout['array']],
    ]
    return commands


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    commands = plan(args.config)
    print(json.dumps({'commands': commands}, indent=2), flush=True)
    if args.apply:
        for command in commands:
            subprocess.run(command, check=True)
