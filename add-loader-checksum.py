"""Add the observed NetApp MD5 integrity note to an existing ELF64 wrapper."""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile


def load_segments(image):
    """Return execution identity for comparison before and after note insertion."""
    if image[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected a little-endian ELF64 image')
    offset = struct.unpack_from('<Q', image, 32)[0]
    size, count = struct.unpack_from('<HH', image, 54)
    segments = []
    for index in range(count):
        header = struct.unpack_from('<IIQQQQQQ', image, offset + index * size)
        kind, flags, start, virtual, physical, file_size, memory_size, alignment = header
        if kind == 1:
            segments.append((flags, virtual, physical, memory_size, alignment,
                             image[start:start + file_size]))
    return struct.unpack_from('<Q', image, 24)[0], segments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise FileExistsError(args.destination)
    original = args.source.read_bytes()
    identity = load_segments(original)
    name = b'Network Appliance\0\0\0'
    note = struct.pack('<III', len(name), 16, 1) + name + bytes(16)
    with tempfile.TemporaryDirectory() as directory:
        note_path = Path(directory) / 'checksum.note'
        note_path.write_bytes(note)
        subprocess.run([
            'objcopy', '--add-section', f'ntap_checksum={note_path}',
            '--set-section-flags', 'ntap_checksum=contents,readonly',
            str(args.source), str(args.destination),
        ], check=True)
    image = bytearray(args.destination.read_bytes())
    offset = struct.unpack_from('<Q', image, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', image, 58)
    names_header = offset + names_index * size
    names_start, names_size = struct.unpack_from('<QQ', image, names_header + 24)
    names = image[names_start:names_start + names_size]
    matches = []
    for index in range(count):
        header = offset + index * size
        name_offset = struct.unpack_from('<I', image, header)[0]
        section_name = bytes(names[name_offset:]).split(b'\0', 1)[0]
        if section_name == b'ntap_checksum':
            matches.append(header)
    if len(matches) != 1:
        raise ValueError('Expected exactly one checksum section')
    header = matches[0]
    struct.pack_into('<I', image, header + 4, 7)  # SHT_NOTE
    start, length = struct.unpack_from('<QQ', image, header + 24)
    if image[start:start + length] != note:
        raise ValueError('Unexpected checksum note layout')
    digest_start = start + 32
    digest = hashlib.md5(image).digest()  # Loader integrity format, not authentication.
    image[digest_start:digest_start + 16] = digest
    check = bytearray(image)
    check[digest_start:digest_start + 16] = bytes(16)
    if hashlib.md5(check).digest() != digest:
        raise ValueError('Checksum verification failed')
    if load_segments(image) != identity:
        raise ValueError('Execution entry or loadable segment contents changed')
    args.destination.write_bytes(image)
    print('Execution entry and loadable segments unchanged; integrity note verified.')
    print('SHA256:', hashlib.sha256(image).hexdigest())


if __name__ == '__main__':
    main()
