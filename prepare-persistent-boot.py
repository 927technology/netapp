"""Prepare a persistent-root initramfs tree without changing device boot media."""
import argparse
import json
import lzma
from pathlib import Path
import re
import shlex
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-work-dir', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--kernel-modules', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())['linux']
    args.work_dir.mkdir(exist_ok=False)
    root = args.work_dir / 'root'
    shutil.copytree(args.base_work_dir / 'root', root, symlinks=True)
    (args.work_dir / 'downloads').symlink_to(
        (args.base_work_dir / 'downloads').resolve(), target_is_directory=True)
    kernel = config['boot']['kernel']
    module_root = args.kernel_modules
    destination = root / 'lib/modules' / kernel
    index = {path.name.removesuffix('.ko.xz').replace('-', '_'): path
             for path in module_root.rglob('*.ko.xz')}
    copied = set()

    def module(name):
        name = name.replace('-', '_')
        if name in copied:
            return
        path = index[name]
        dependencies = subprocess.run(
            ['modinfo', '-F', 'depends', str(path)], check=True,
            capture_output=True, text=True).stdout.strip()
        for dependency in filter(None, dependencies.split(',')):
            module(dependency)
        output = destination / path.relative_to(module_root).with_suffix('')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(lzma.decompress(path.read_bytes()))
        copied.add(name)

    for name in ['md_mod', 'raid1', 'crc32c_generic', 'ext4']:
        module(name)
    for name in ['modules.builtin', 'modules.builtin.modinfo', 'modules.order']:
        shutil.copyfile(module_root / name, destination / name)
    subprocess.run(['depmod', '-b', str(root), kernel], check=True)
    library = args.runtime / 'usr/lib/x86_64-linux-gnu'
    loader = library / 'ld-linux-x86-64.so.2'
    (root / 'usr/sbin').mkdir(parents=True, exist_ok=True)
    (root / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True, exist_ok=True)
    for name in ['mdadm', 'e2fsck', 'blkid']:
        executable = args.runtime / 'usr/sbin' / name
        if not executable.exists():
            executable = args.runtime.parent / 'rootfs/usr/sbin' / name
        result = subprocess.run(
            [str(loader), '--library-path', str(library), '--list', str(executable)],
            check=True, capture_output=True, text=True)
        shutil.copyfile(executable, root / 'usr/sbin' / name)
        (root / 'usr/sbin' / name).chmod(0o755)
        for value in re.findall(r'=> (/\S+)', result.stdout) + [str(loader)]:
            path = Path(value)
            if not path.is_relative_to(args.runtime):
                raise ValueError('Dependency escaped the staged Debian runtime: ' + value)
            target = root / 'usr/lib/x86_64-linux-gnu' / path.name
            shutil.copyfile(path, target)
            target.chmod(0o755)
    (root / 'etc').mkdir(exist_ok=True)
    values = {'ROOT_HOSTNAME': config['hostname'],
              'ROOT_UUID': config['os']['root']['filesystem_uuid']}
    (root / 'etc/netapp-root.conf').write_text(''.join(
        name + '=' + shlex.quote(value) + '\n' for name, value in sorted(values.items())))
    (root / 'etc/mdadm.conf').write_text(
        'DEVICE partitions\nARRAY /dev/md0 UUID='
        + config['os']['root']['array_uuid'] + '\n')
    print('Prepared root assembly and filesystem modules:', ', '.join(sorted(copied)))
    print('Kernel options:', config['boot']['kernel_options'])


if __name__ == '__main__':
    main()
