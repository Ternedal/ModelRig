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

static int current_directory(void) {
    HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD wide_length = GetCurrentDirectoryW(0, NULL);
    WCHAR *wide_path;
    int utf8_length;
    char *utf8_path;
    int result;

    if (wide_length == 0) {
        return 30;
    }
    wide_path = (WCHAR *)HeapAlloc(
        GetProcessHeap(), HEAP_ZERO_MEMORY, wide_length * sizeof(WCHAR)
    );
    if (wide_path == NULL) {
        return 31;
    }
    if (GetCurrentDirectoryW(wide_length, wide_path) == 0) {
        HeapFree(GetProcessHeap(), 0, wide_path);
        return 32;
    }
    utf8_length = WideCharToMultiByte(
        CP_UTF8, WC_ERR_INVALID_CHARS, wide_path, -1, NULL, 0, NULL, NULL
    );
    if (utf8_length <= 1) {
        HeapFree(GetProcessHeap(), 0, wide_path);
        return 33;
    }
    utf8_path = (char *)HeapAlloc(GetProcessHeap(), 0, (SIZE_T)utf8_length);
    if (utf8_path == NULL) {
        HeapFree(GetProcessHeap(), 0, wide_path);
        return 34;
    }
    if (WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            wide_path,
            -1,
            utf8_path,
            utf8_length,
            NULL,
            NULL
        ) == 0) {
        HeapFree(GetProcessHeap(), 0, utf8_path);
        HeapFree(GetProcessHeap(), 0, wide_path);
        return 35;
    }
    result = write_all(stdout_handle, utf8_path, (DWORD)(utf8_length - 1)) ? 0 : 36;
    HeapFree(GetProcessHeap(), 0, utf8_path);
    HeapFree(GetProcessHeap(), 0, wide_path);
    return result;
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
    if (strcmp(argv[1], "cwd") == 0) {
        return current_directory();
    }
    return 3;
}
