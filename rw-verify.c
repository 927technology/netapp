#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

/* Destructive sampled test. Caller must verify serial/WWN and authorization.
 * O_EXCL excludes mounted block devices; O_DIRECT avoids page-cache reads.
 * Writes cover only three regions; optional --read-all reads every logical
 * block. Neither mode provides a power-loss durability test.
 */
static void fail(const char *message)
{
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(EXIT_FAILURE);
}

static uint64_t next_value(uint64_t *state)
{
    uint64_t value = (*state += UINT64_C(0x9e3779b97f4a7c15));
    value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}

int main(int argc, char **argv)
{
    const size_t length = 8 * 1024 * 1024;
    uint64_t capacity = 0;
    uint64_t expected;
    uint64_t offsets[3];
    uint64_t seed = 0;
    uint64_t *written = NULL;
    void *read_back = NULL;
    char *end = NULL;
    struct stat info;
    int sector_size = 0;
    int read_only = 1;
    int fd;

    if (argc != 4 &&
        !(argc == 5 &&
            !strcmp(argv[4], "--read-all"))) {
        fprintf(stderr, "Usage: %s BLOCK_DEVICE EXPECTED_BYTES SERIAL_SEED [--read-all]\n", argv[0]);
        return EXIT_FAILURE;
    }
    errno = 0;
    expected = strtoull(argv[2], &end, 10);
    if (errno ||
        !argv[2][0] ||
        *end ||
        expected < 4 * length) {
        fprintf(stderr, "Invalid expected capacity\n");
        return EXIT_FAILURE;
    }
    fd = open(argv[1], O_RDWR | O_DIRECT | O_EXCL | O_CLOEXEC);
    if (fd < 0)
        fail("open block device exclusively");
    if (fstat(fd, &info) < 0)
        fail("fstat");
    if (!S_ISBLK(info.st_mode)) {
        fprintf(stderr, "Refusing a non-block device\n");
        return EXIT_FAILURE;
    }
    if (ioctl(fd, BLKGETSIZE64, &capacity) < 0 ||
        ioctl(fd, BLKSSZGET, &sector_size) < 0 ||
        ioctl(fd, BLKROGET, &read_only) < 0)
        fail("block geometry");
    if (capacity != expected ||
        sector_size != 512 ||
        read_only) {
        fprintf(stderr, "Refusing unexpected capacity, sector size or read-only device\n");
        return EXIT_FAILURE;
    }
    if (posix_memalign((void **)&written, 4096, length) ||
        posix_memalign(&read_back, 4096, length)) {
        fprintf(stderr, "Aligned buffer allocation failed\n");
        return EXIT_FAILURE;
    }
    for (const unsigned char *p = (const unsigned char *)argv[3]; *p; p++)
        seed = seed * 131 + *p;
    offsets[0] = 0;
    offsets[1] = (capacity / 2) & ~UINT64_C(4095);
    offsets[2] = (capacity - length) & ~UINT64_C(4095);
    for (unsigned region = 0; region < 3; region++) {
        uint64_t state = seed ^ offsets[region] ^ region;
        for (size_t i = 0; i < length / sizeof(*written); i++)
            written[i] = next_value(&state);
        if (pwrite(fd, written, length, (off_t)offsets[region]) != (ssize_t)length) {
            fprintf(stderr, "Write failed or returned a short count in region %u\n", region);
            return EXIT_FAILURE;
        }
        if (fsync(fd) < 0)
            fail("fsync");
        memset(read_back, 0, length);
        if (pread(fd, read_back, length, (off_t)offsets[region]) != (ssize_t)length) {
            fprintf(stderr, "Read failed or returned a short count in region %u\n", region);
            return EXIT_FAILURE;
        }
        if (memcmp(written, read_back, length)) {
            fprintf(stderr, "Data mismatch in region %u\n", region);
            return EXIT_FAILURE;
        }
        printf("REGION_PASS offset=%" PRIu64 " bytes=%zu\n", offsets[region], length);
        fflush(stdout);
    }
    puts("WRITE_READ_VERIFIED");
    fflush(stdout);
    if (argc == 5) {
        uint64_t completed = 0;
        uint64_t next_progress = capacity / 20;
        while (completed < capacity) {
            size_t count = capacity - completed < length ?
                (size_t)(capacity - completed) : length;
            if (pread(fd, read_back, count, (off_t)completed) != (ssize_t)count) {
                fprintf(stderr, "Full read failed or short count at byte %" PRIu64 "\n", completed);
                return EXIT_FAILURE;
            }
            completed += count;
            if (completed >= next_progress) {
                printf("FULL_READ_PROGRESS bytes=%" PRIu64 " percent=%.2f\n",
                    completed, 100.0 * (double)completed / (double)capacity);
                fflush(stdout);
                next_progress = completed + capacity / 20;
            }
        }
        printf("FULL_READ_VERIFIED bytes=%" PRIu64 "\n", completed);
        fflush(stdout);
    }
    if (close(fd) < 0)
        fail("close");
    free(written);
    free(read_back);
    return EXIT_SUCCESS;
}
