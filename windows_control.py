"""Small Windows desktop helpers built only with Python's standard library."""

from __future__ import annotations

import ctypes
import struct
import sys
import zlib
from functools import lru_cache
from ctypes import wintypes


@lru_cache(maxsize=1)
def _windows_dlls():
    if sys.platform != "win32":
        raise OSError("Desktop control is available only on Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    return user32, gdi32


def screen_size() -> tuple[int, int]:
    user32, _ = _windows_dlls()
    user32.GetSystemMetrics.restype = ctypes.c_int
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move_pointer(x: int, y: int) -> None:
    user32, _ = _windows_dlls()
    if not user32.SetCursorPos(int(x), int(y)):
        raise ctypes.WinError(ctypes.get_last_error())


def click_pointer() -> None:
    user32, _ = _windows_dlls()
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left button down
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left button up


def scroll_wheel(amount: int) -> None:
    user32, _ = _windows_dlls()
    user32.mouse_event(0x0800, 0, 0, int(amount) * 120, 0)


def _send_key(vk: int, flags: int = 0, scan: int = 0) -> None:
    user32, _ = _windows_dlls()

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ii", INPUTUNION)]

    event = INPUT(type=1, ii=INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def type_text(text: str) -> None:
    for char in text:
        encoded = char.encode("utf-16-le", errors="replace")
        for offset in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[offset:offset + 2], "little")
            _send_key(0, 0x0004, unit)
            _send_key(0, 0x0004 | 0x0002, unit)


KEYS = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "backspace": 0x08,
    "delete": 0x2E, "space": 0x20, "ctrl": 0x11, "alt": 0x12,
    "shift": 0x10, "l": 0x4C, "f": 0x46, "c": 0x43, "v": 0x56, "a": 0x41,
}


def press_key(key: str) -> None:
    parts = key.lower().split("+")
    codes = [KEYS[part] for part in parts]
    for code in codes:
        _send_key(code)
    for code in reversed(codes):
        _send_key(code, 0x0002)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)


def screenshot_png() -> bytes:
    """Capture the primary display and encode it as PNG without third-party packages."""
    user32, gdi32 = _windows_dlls()
    width, height = screen_size()
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, 0, 0, 0x00CC0020):
        raise ctypes.WinError(ctypes.get_last_error())
    gdi32.SelectObject(memory_dc, previous)
    info = BITMAPINFO()
    info.bmiHeader = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
    raw = ctypes.create_string_buffer(width * height * 4)
    lines = gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, ctypes.byref(info), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(None, screen_dc)
    if lines != height:
        raise ctypes.WinError(ctypes.get_last_error())

    pixels = memoryview(raw).cast("B")
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        start = y * stride
        for x in range(start, start + stride, 4):
            rows.extend((pixels[x + 2], pixels[x + 1], pixels[x], 255))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(rows, 3)) + _png_chunk(b"IEND", b"")
