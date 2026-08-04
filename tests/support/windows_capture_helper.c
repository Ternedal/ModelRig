#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <wchar.h>

#define CHUNK_BYTES 4096
#define CHUNK_COUNT 64
#define PATH_CAPACITY 32768

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

static int module_paths(
    WCHAR *module_path,
    WCHAR *support_path,
    WCHAR *renamed_path,
    WCHAR *injected_path
) {
    DWORD length = GetModuleFileNameW(NULL, module_path, PATH_CAPACITY);
    WCHAR *separator;
    size_t directory_length;

    if (length == 0 || length >= PATH_CAPACITY) {
        return 0;
    }
    separator = wcsrchr(module_path, L'\\');
    if (separator == NULL) {
        return 0;
    }
    directory_length = (size_t)(separator - module_path);
    if (_snwprintf_s(
            support_path,
            PATH_CAPACITY,
            _TRUNCATE,
            L"%.*s\\support\\runtime.dat",
            (int)directory_length,
            module_path
        ) < 0) {
        return 0;
    }
    if (_snwprintf_s(
            renamed_path,
            PATH_CAPACITY,
            _TRUNCATE,
            L"%.*s\\support\\runtime-renamed.dat",
            (int)directory_length,
            module_path
        ) < 0) {
        return 0;
    }
    if (_snwprintf_s(
            injected_path,
            PATH_CAPACITY,
            _TRUNCATE,
            L"%.*s\\support\\injected.dll",
            (int)directory_length,
            module_path
        ) < 0) {
        return 0;
    }
    return 1;
}

static int write_open_was_denied(const WCHAR *path) {
    HANDLE handle = CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) {
        return 1;
    }
    CloseHandle(handle);
    return 0;
}

static int runtime_mutation_probe(void) {
    HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    WCHAR module_path[PATH_CAPACITY];
    WCHAR support_path[PATH_CAPACITY];
    WCHAR renamed_path[PATH_CAPACITY];
    WCHAR injected_path[PATH_CAPACITY];
    HANDLE injected;

    if (!module_paths(module_path, support_path, renamed_path, injected_path)) {
        return 40;
    }
    if (!write_open_was_denied(module_path)) {
        return 41;
    }
    if (!write_open_was_denied(support_path)) {
        return 42;
    }
    if (DeleteFileW(support_path)) {
        return 43;
    }
    if (MoveFileExW(support_path, renamed_path, MOVEFILE_REPLACE_EXISTING)) {
        MoveFileExW(renamed_path, support_path, MOVEFILE_REPLACE_EXISTING);
        return 44;
    }
    injected = CreateFileW(
        injected_path,
        GENERIC_WRITE,
        FILE_SHARE_READ,
        NULL,
        CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (injected != INVALID_HANDLE_VALUE) {
        CloseHandle(injected);
        DeleteFileW(injected_path);
        return 45;
    }
    return write_all(stdout_handle, "RUNTIME-IMMUTABLE\n", 18) ? 0 : 46;
}

static int hold_runtime_guard(void) {
    HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    HANDLE marker = CreateFileW(
        L"guard-ready.txt",
        GENERIC_WRITE,
        FILE_SHARE_READ,
        NULL,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    DWORD written = 0;
    if (marker == INVALID_HANDLE_VALUE) {
        return 50;
    }
    if (!WriteFile(marker, "ready\n", 6, &written, NULL) || written != 6) {
        CloseHandle(marker);
        return 51;
    }
    CloseHandle(marker);
    if (!write_all(stdout_handle, "GUARD-READY\n", 12)) {
        return 52;
    }
    Sleep(5000);
    DeleteFileW(L"guard-ready.txt");
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
    if (strcmp(argv[1], "cwd") == 0) {
        return current_directory();
    }
    if (strcmp(argv[1], "mutate") == 0) {
        return runtime_mutation_probe();
    }
    if (strcmp(argv[1], "hold") == 0) {
        return hold_runtime_guard();
    }
    return 3;
}
