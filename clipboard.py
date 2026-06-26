"""
Windows clipboard reader using win32 API. Reads Unicode text reliably.
"""
import time
import ctypes
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def get_clipboard_text() -> str:
    """
    Read Unicode text from Windows clipboard.
    Returns empty string on any failure.
    """
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        for attempt in range(3):
            if not user32.OpenClipboard(None):
                time.sleep(0.05)
                continue
            try:
                if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    return ""
                h_data = user32.GetClipboardData(CF_UNICODETEXT)
                if not h_data:
                    return ""
                size = kernel32.GlobalSize(h_data)
                if size == 0 or size > 10_000_000:
                    return ""
                ptr = kernel32.GlobalLock(h_data)
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
                    kernel32.GlobalUnlock(h_data)
            finally:
                user32.CloseClipboard()
            break
        return ""
    except Exception:
        return ""


def get_clipboard_text_safe() -> str:
    return get_clipboard_text() or ""