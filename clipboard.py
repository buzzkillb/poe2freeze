"""
Windows clipboard reader using win32 API. Reads Unicode text reliably.
"""
import time
import ctypes
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Configure Win32 FFI once at module load
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
_user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = wintypes.LPVOID
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalSize.restype = ctypes.c_size_t


def get_clipboard_text() -> str:
    """Read Unicode text from Windows clipboard. Returns empty string on failure."""
    try:
        for attempt in range(3):
            if not _user32.OpenClipboard(None):
                time.sleep(0.05)
                continue
            try:
                if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    return ""
                h_data = _user32.GetClipboardData(CF_UNICODETEXT)
                if not h_data:
                    return ""
                size = _kernel32.GlobalSize(h_data)
                if size == 0 or size > 10_000_000:
                    return ""
                ptr = _kernel32.GlobalLock(h_data)
                if not ptr:
                    return ""
                try:
                    text_bytes = ctypes.string_at(ptr, size)
                    try:
                        text = text_bytes.decode("utf-16-le", errors="ignore")
                        text = text.rstrip("\x00")
                        return text
                    except Exception:
                        return ""
                finally:
                    _kernel32.GlobalUnlock(h_data)
            finally:
                _user32.CloseClipboard()
            break
        return ""
    except Exception:
        return ""


def get_clipboard_text_safe() -> str:
    return get_clipboard_text() or ""