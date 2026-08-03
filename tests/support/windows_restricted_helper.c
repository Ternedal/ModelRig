#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>

static BOOL can_read(const wchar_t *path) {
    HANDLE handle = CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) {
        return FALSE;
    }
    CloseHandle(handle);
    return TRUE;
}

static BOOL can_write(const wchar_t *path) {
    static const char payload[] = "appcontainer-write-ok";
    HANDLE handle = CreateFileW(
        path,
        GENERIC_WRITE,
        0,
        NULL,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (handle == INVALID_HANDLE_VALUE) {
        return FALSE;
    }
    DWORD written = 0;
    BOOL ok = WriteFile(
        handle,
        payload,
        (DWORD)(sizeof(payload) - 1),
        &written,
        NULL
    );
    BOOL closed = CloseHandle(handle);
    return ok && closed && written == (DWORD)(sizeof(payload) - 1);
}

static BOOL query_token_flag(TOKEN_INFORMATION_CLASS information_class) {
    HANDLE token = NULL;
    DWORD value = 0;
    DWORD returned = 0;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        return FALSE;
    }
    BOOL ok = GetTokenInformation(
        token,
        information_class,
        &value,
        sizeof(value),
        &returned
    );
    CloseHandle(token);
    return ok && returned == sizeof(value) && value != 0;
}

static const char *json_bool(BOOL value) {
    return value ? "true" : "false";
}

int wmain(int argc, wchar_t **argv) {
    if (argc != 6) {
        return 2;
    }

    BOOL appcontainer = query_token_flag(TokenIsAppContainer);
    BOOL lowbox = query_token_flag(TokenIsLessPrivilegedAppContainer);
    BOOL restricted = FALSE;
    HANDLE token = NULL;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        restricted = IsTokenRestricted(token);
        CloseHandle(token);
    }
    BOOL inside_read = can_read(argv[1]);
    BOOL outside_read = can_read(argv[2]);
    BOOL inside_write = can_write(argv[3]);
    BOOL outside_write = can_write(argv[4]);

    char receipt[640];
    int length = _snprintf_s(
        receipt,
        sizeof(receipt),
        _TRUNCATE,
        "{\"appcontainer\":%s,\"lpac\":%s,\"restricted\":%s,"
        "\"inside_read\":%s,\"outside_read\":%s,"
        "\"inside_write\":%s,\"outside_write\":%s}",
        json_bool(appcontainer),
        json_bool(lowbox),
        json_bool(restricted),
        json_bool(inside_read),
        json_bool(outside_read),
        json_bool(inside_write),
        json_bool(outside_write)
    );
    if (length <= 0) {
        return 3;
    }

    HANDLE result = CreateFileW(
        argv[5],
        GENERIC_WRITE,
        0,
        NULL,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (result == INVALID_HANDLE_VALUE) {
        return 4;
    }
    DWORD written = 0;
    BOOL ok = WriteFile(result, receipt, (DWORD)length, &written, NULL);
    BOOL closed = CloseHandle(result);
    if (!ok || !closed || written != (DWORD)length) {
        return 5;
    }
    return 0;
}
