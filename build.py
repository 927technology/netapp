"""Build a RAM-only Linux ELF without touching attached target storage."""
from pathlib import Path
import argparse,gzip,hashlib,stat,struct,subprocess
parser=argparse.ArgumentParser()
parser.add_argument('--init', type=Path)
parser.add_argument('--kernel-options')
parser.add_argument('--work-dir',required=True)
args=parser.parse_args()
p=Path(args.work_dir).resolve();root=p/'root';source=Path(__file__).resolve().parent
init=root/'init'
init.write_text((args.init or source/'init').read_text())
options = args.kernel_options or 'earlycon=uart8250,io,0x3f8 nokaslr loglevel=7 ignore_loglevel rdinit=/init panic=0 ro noresume maxcpus=1'
if '\0' in options or '\n' in options:
    raise ValueError('Kernel options must be a single line without NUL bytes')
(p/'kernel-options.bin').write_bytes(options.encode() + b'\0')
items=[('.',stat.S_IFDIR|0o755,b'',0,0)]
for f in sorted(root.rglob('*')):
 name=str(f.relative_to(root))
 if f.is_symlink():mode=stat.S_IFLNK|0o777;data=str(f.readlink()).encode()
 elif f.is_dir():mode=stat.S_IFDIR|0o755;data=b''
 else:
  executable = name in ['init', 'bin/busybox'] or bool(f.stat().st_mode & 0o111)
  mode = stat.S_IFREG | (0o755 if executable else 0o644)
  data = f.read_bytes()
 items.append((name,mode,data,0,0))
items.append(('dev/console',stat.S_IFCHR|0o600,b'',5,1));archive=bytearray()
for ino,(name,mode,data,major,minor) in enumerate(items,1):
 n=name.encode()+b'\0';fields=[ino,mode,0,0,1,0,len(data),0,0,major,minor,len(n),0]
 archive+=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)+n;archive+=b'\0'*(-len(archive)%4);archive+=data;archive+=b'\0'*(-len(archive)%4)
n=b'TRAILER!!!\0';fields=[0,0,0,0,1,0,0,0,0,0,0,len(n),0];archive+=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)+n;archive+=b'\0'*(-len(archive)%512)
(p/'initramfs.cpio.gz').write_bytes(gzip.compress(archive,mtime=0))
kernel=(p/'downloads/linux').read_bytes();expected=[l.split()[0] for l in (p/'downloads/SHA256SUMS').read_text().splitlines() if l.split()[-1].removeprefix('./')=='netboot/debian-installer/amd64/linux'];assert hashlib.sha256(kernel).hexdigest()==expected[0]
assert kernel[0x202:0x206]==b'HdrS';setup_size=((kernel[0x1f1] or 4)+1)*512;setup=bytearray(kernel[:setup_size]);initrd_size=(p/'initramfs.cpio.gz').stat().st_size
assert max(0x100000,struct.unpack_from('<Q',kernel,0x258)[0])+struct.unpack_from('<I',kernel,0x260)[0]<0x10000000
assert 0x18000000+initrd_size-1<=struct.unpack_from('<I',kernel,0x22c)[0]
struct.pack_into('<H',setup,0x1fa,0xffff);setup[0x210]=0xff;setup[0x211]|=0x80
struct.pack_into('<I',setup,0x214,0x100000);struct.pack_into('<II',setup,0x218,0x18000000,initrd_size);struct.pack_into('<H',setup,0x224,0xde00);struct.pack_into('<I',setup,0x228,0x20000)
(p/'setup.bin').write_bytes(setup);(p/'protected.bin').write_bytes(kernel[setup_size:])
subprocess.run(['gcc','-c','-nostdlib','-fno-pie','-m64',str(source/'bootstrap.S'),'-o',str(p/'bootstrap.o')],check=True,cwd=p)
subprocess.run(['ld','-static','-nostdlib','-z','max-page-size=0x1000','-T',str(source/'bootstrap.ld'),str(p/'bootstrap.o'),'-o',str(p/'linux-test.elf')],check=True)
print('Initramfs:',initrd_size,'bytes; ELF:',(p/'linux-test.elf').stat().st_size,'bytes')
print('ELF SHA256:',hashlib.sha256((p/'linux-test.elf').read_bytes()).hexdigest())

# Reject load segments outside the tested wrapper window or overlapping initrd.
image=(p/'linux-test.elf').read_bytes()
phoff=struct.unpack_from('<Q',image,32)[0]
phsize,phnum=struct.unpack_from('<HH',image,54)
regions=[]
for i in range(phnum):
    kind,flags,offset,vaddr,paddr,filesz,memsz,align=struct.unpack_from('<IIQQQQQQ',image,phoff+i*phsize)
    if kind!=1:
        continue
    assert filesz<=memsz
    assert 0x10000000<=paddr<paddr+memsz<0x18000000
    assert vaddr==paddr
    regions.append((paddr,paddr+memsz))
regions.sort()
assert all(a[1]<=b[0] for a,b in zip(regions,regions[1:]))
print('ELF physical segment bounds verified.')
