#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>

#define CHUNK_BYTES 4096
#define CHUNK_COUNT 64

static int write_all(HANDLE handle, const char *data, DWORD size) {
    DWORD offset = 0;
    while (offset < size) {
        DWORD written = 0;
        if (!WriteFile(handle, data + offset, size - offset, &written, NULL)) {
            return 0;
        }
        if (written == 0) {
            return 0;
        }
        offset += written;
    }
    return 1;
}

static int burst(void) {
    HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    HANDLE stderr_handle = GetStdHandle(STD_ERROR_HANDLE);
    char stdout_chunk[CHUNK_BYTES];
    char stderr_chunk[CHUNK_BYTES];
    int index;

    memset(stdout_chunk, 'A', sizeof(stdout_chunk));
    memset(stderr_chunk, 'B', sizeof(stderr_chunk));
    if (!write_all(stdout_handle, "STDOUT-BEGIN\n", 13)) {
        return 10;
    }
    if (!write_all(stderr_handle, "STDERR-BEGIN\n", 13)) {
        return 11;
    }
    for (index = 0; index < CHUNK_COUNT; ++index) {
        if (!write_all(stdout_handle, stdout_chunk, sizeof(stdout_chunk))) {
            return 12;
        }
        if (!write_all(stderr_handle, stderr_chunk, sizeof(stderr_chunk))) {
            return 13;
        }
    }
    return 0;
}

static int sleep_after_marker(void) {
    HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    if (!write_all(stdout_handle, "BEFORE-TIMEOUT\n", 15)) {
        return 20;
    }
    Sleep(60000);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 2;
    }
    if (strcmp(argv[1], "burst") == 0) {
        return burst();
    }
    if (strcmp(argv[1], "sleep") == 0) {
        return sleep_after_marker();
    }
    return 3;
}
