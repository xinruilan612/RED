"""Owner-only Windows files, using native ACLs rather than ineffective chmod bits.

This module is imported only on Windows. Files are born with a protected DACL;
no secret is written while inherited, potentially public permissions are active.
"""
import ctypes as c
from ctypes import wintypes as w
import msvcrt
import os


class SecurityAttributes(c.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]


class Acl(c.Structure):
    _fields_ = [('revision', w.BYTE), ('reserved', w.BYTE), ('size', w.WORD),
                ('count', w.WORD), ('reserved2', w.WORD)]


class AllowedAce(c.Structure):
    _fields_ = [('kind', w.BYTE), ('flags', w.BYTE), ('size', w.WORD),
                ('mask', w.DWORD), ('sid_start', w.DWORD)]


kernel = c.WinDLL('kernel32', use_last_error=True)
security = c.WinDLL('advapi32', use_last_error=True)
ptr = c.c_void_p
pptr = c.POINTER(ptr)


def _bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


_current_process = _bind(kernel, 'GetCurrentProcess', w.HANDLE)
_close = _bind(kernel, 'CloseHandle', w.BOOL, w.HANDLE)
_free = _bind(kernel, 'LocalFree', ptr, ptr)
_open_token = _bind(security, 'OpenProcessToken', w.BOOL, w.HANDLE, w.DWORD, c.POINTER(w.HANDLE))
_token_info = _bind(security, 'GetTokenInformation', w.BOOL, w.HANDLE, c.c_int, ptr, w.DWORD, c.POINTER(w.DWORD))
_sid_string = _bind(security, 'ConvertSidToStringSidW', w.BOOL, ptr, pptr)
_descriptor = _bind(security, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', w.BOOL,
                    w.LPCWSTR, w.DWORD, pptr, c.POINTER(w.DWORD))
_create = _bind(kernel, 'CreateFileW', w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
               c.POINTER(SecurityAttributes), w.DWORD, w.DWORD, w.HANDLE)
_get_security = _bind(security, 'GetNamedSecurityInfoW', w.DWORD, w.LPCWSTR, c.c_int,
                     w.DWORD, pptr, pptr, pptr, pptr, pptr)
_get_control = _bind(security, 'GetSecurityDescriptorControl', w.BOOL, ptr,
                    c.POINTER(w.WORD), c.POINTER(w.DWORD))
_get_ace = _bind(security, 'GetAce', w.BOOL, ptr, w.DWORD, pptr)


def _check(ok):
    if not ok:
        raise c.WinError(c.get_last_error())


def sid_text(sid):
    text = ptr()
    _check(_sid_string(sid, c.byref(text)))
    try:
        return c.wstring_at(text)
    finally:
        _free(text)


def current_sid():
    token = w.HANDLE()
    _check(_open_token(_current_process(), 8, c.byref(token)))  # TOKEN_QUERY
    try:
        length = w.DWORD()
        _token_info(token, 1, None, 0, c.byref(length))  # TokenUser
        if not length.value:
            raise c.WinError(c.get_last_error())
        buffer = c.create_string_buffer(length.value)
        _check(_token_info(token, 1, buffer, length, c.byref(length)))
        return sid_text(c.cast(buffer, pptr)[0])
    finally:
        _close(token)


def create_private_fd(path):
    """CREATE_NEW prevents replacing another file; the ACL is set at creation."""
    sid, descriptor = current_sid(), ptr()
    _check(_descriptor(f'O:{sid}D:P(A;;FA;;;{sid})', 1, c.byref(descriptor), None))
    try:
        attributes = SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
        handle = _create(str(path), 0xC0000000, 7, c.byref(attributes), 1, 0x80, None)
        if handle == w.HANDLE(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            _close(handle)
            raise
    finally:
        _free(descriptor)


def is_owner_only(path):
    """Fail closed on null/inherited/unrecognized ACLs or any additional grantee."""
    owner, dacl, descriptor = ptr(), ptr(), ptr()
    result = _get_security(str(path), 1, 5, c.byref(owner), None,
                           c.byref(dacl), None, c.byref(descriptor))
    if result:
        raise c.WinError(result)
    try:
        sid = current_sid()
        control, revision = w.WORD(), w.DWORD()
        _check(_get_control(descriptor, c.byref(control), c.byref(revision)))
        if not owner or sid_text(owner) != sid or not dacl or not control.value & 0x1000:
            return False  # SE_DACL_PROTECTED
        acl = c.cast(dacl, c.POINTER(Acl)).contents
        if acl.count != 1:
            return False
        address = ptr()
        _check(_get_ace(dacl, 0, c.byref(address)))
        ace = c.cast(address, c.POINTER(AllowedAce)).contents
        return (ace.kind == 0 and ace.flags == 0 and ace.mask == 0x1F01FF
                and sid_text(address.value + AllowedAce.sid_start.offset) == sid)
    finally:
        _free(descriptor)
