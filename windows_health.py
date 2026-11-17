"""Read Windows CPU, memory, battery, disk, and uptime with the standard library."""

from __future__ import annotations

import ctypes
import shutil
import sys
from ctypes import wintypes
from pathlib import Path
from typing import NotRequired, TypedDict

_last_cpu: tuple[int, int, int] | None = None


class RamReading(TypedDict):
    used_percent: int
    total_gb: float
    available_gb: float


class BatteryReading(TypedDict):
    available: bool
    percent: int | None
    charging: bool


class DiskReading(TypedDict):
    used_percent: int
    free_gb: float
    total_gb: float


class LaptopHealth(TypedDict):
    available: bool
    message: NotRequired[str]
    cpu_percent: NotRequired[int | None]
    ram: NotRequired[RamReading | None]
    battery: NotRequired[BatteryReading]
    disk: NotRequired[DiskReading]
    uptime_hours: NotRequired[float]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE), ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def _filetime_value(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def get_laptop_health() -> LaptopHealth:
    global _last_cpu
    if sys.platform != "win32":
        return {"available": False, "message": "Windows system health readings are unavailable on this operating system."}

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.GetSystemTimes.restype = wintypes.BOOL
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    cpu_percent: int | None = None
    if kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        current = (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))
        if _last_cpu is not None:
            idle_delta = current[0] - _last_cpu[0]
            total_delta = (current[1] - _last_cpu[1]) + (current[2] - _last_cpu[2])
            if total_delta > 0:
                cpu_percent = round(max(0, min(100, 100 * (1 - idle_delta / total_delta))))
        _last_cpu = current

    memory = MEMORYSTATUSEX()
    memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    ram: RamReading | None = None
    if kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        ram = {"used_percent": int(memory.dwMemoryLoad), "total_gb": round(memory.ullTotalPhys / (1024 ** 3), 1), "available_gb": round(memory.ullAvailPhys / (1024 ** 3), 1)}

    power = SYSTEM_POWER_STATUS()
    kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
    kernel32.GetSystemPowerStatus.restype = wintypes.BOOL
    battery: BatteryReading = {"available": False, "percent": None, "charging": False}
    if kernel32.GetSystemPowerStatus(ctypes.byref(power)) and power.BatteryFlag != 128:
        battery = {"available": True, "percent": int(power.BatteryLifePercent) if power.BatteryLifePercent <= 100 else None, "charging": power.ACLineStatus == 1}

    disk_path = Path.home().anchor or "C:\\"
    disk_usage = shutil.disk_usage(disk_path)
    disk: DiskReading = {"used_percent": round((disk_usage.total - disk_usage.free) / disk_usage.total * 100), "free_gb": round(disk_usage.free / (1024 ** 3), 1), "total_gb": round(disk_usage.total / (1024 ** 3), 1)}
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    uptime_minutes = int(kernel32.GetTickCount64() // 60000)
    return {
        "available": True,
        "cpu_percent": cpu_percent,
        "ram": ram,
        "battery": battery,
        "disk": disk,
        "uptime_hours": round(uptime_minutes / 60, 1),
    }
