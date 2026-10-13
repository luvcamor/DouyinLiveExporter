"""Locate MuMu's bundled ADB without assuming an installation drive."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def _location(value):
    if not isinstance(value, str):
        return None
    value = os.path.expandvars(value.strip())
    if value.startswith('"'):
        value = value.split('"', 2)[1]
    else:
        # Registry display icons/uninstall commands may include arguments.
        match = re.match(r'(.+?\.(?:exe|ico|dll))(?:,|\s|$)', value, re.I)
        if match:
            value = match.group(1)
    path = Path(value)
    if not path.is_absolute():
        return None
    return path.parent if path.suffix.lower() in ('.exe', '.ico', '.dll') else path


def _registry_roots():
    if os.name != 'nt':
        return
    import winreg
    uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as parent:
                    for i in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            name = winreg.EnumKey(parent, i)
                            with winreg.OpenKey(parent, name) as key:
                                values = {}
                                for j in range(winreg.QueryInfoKey(key)[1]):
                                    field, value, _ = winreg.EnumValue(key, j)
                                    values[field.lower()] = value
                            label = name + ' ' + str(values.get('displayname', ''))
                            if not any(word in label.lower() for word in ('mumu', 'nemu')):
                                continue
                            for field in ('installlocation', 'displayicon', 'uninstallstring'):
                                root = _location(values.get(field))
                                if root:
                                    yield root
                        except OSError:
                            continue
            except OSError:
                continue


def _process_roots():
    if os.name != 'nt':
        return
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
              "@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Name -match '^(MuMu|Nemu)' } | "
              "Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, timeout=8,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        paths = json.loads(result.stdout.decode('utf-8-sig').strip() or '[]')
        if isinstance(paths, str):
            paths = [paths]
        for value in paths or []:
            root = _location(value)
            if root:
                yield root
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return


def _common_roots():
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA', 'ProgramW6432'):
        value = os.environ.get(variable)
        if not value:
            continue
        for parent in (Path(value), Path(value) / 'Netease'):
            for name in ('MuMuPlayer', 'MuMuPlayer-12.0', 'MuMu', 'Nemu'):
                yield parent / name


def _in_installation(root):
    # Search only known layouts, not an entire disk or unrelated directories.
    roots = [root]
    if root.name.lower() in ('nx_main', 'n_main', 'shell', 'emulator', 'vmonitor', 'bin'):
        roots.append(root.parent)
    for base in roots:
        for suffix in ('adb.exe', 'nx_main/adb.exe', 'n_main/adb.exe', 'shell/adb.exe',
                       'emulator/nemu/vmonitor/bin/adb_server.exe'):
            yield base / suffix
        if base.is_dir():
            for pattern in ('nx_device/*/shell/adb.exe', 'vms/*/shell/adb.exe'):
                yield from base.glob(pattern)


def _candidates(base, override):
    if override:
        expanded = os.path.expandvars(os.path.expanduser(str(override).strip().strip('"')))
        explicit = Path(expanded)
        if not explicit.is_absolute():
            explicit = base / explicit
        if explicit.is_dir():
            yield from _in_installation(explicit)
        else:
            yield explicit
        on_path = shutil.which(expanded)
        if on_path:
            yield Path(on_path)
    yield base / 'adb.exe'
    for roots in (_registry_roots, _process_roots, _common_roots):
        for root in roots():
            yield from _in_installation(root)
    on_path = shutil.which('adb')
    if on_path:
        yield Path(on_path)


def discover_adb(base, override=''):
    """Return the first executable that successfully identifies itself as ADB.

    Explicit configuration wins; stale configuration falls back to discovery.
    Registry/process queries are lazy and stop once a working ADB is found.
    """
    seen = set()
    for path in _candidates(Path(base), override):
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        try:
            result = subprocess.run([str(path), 'version'], capture_output=True, timeout=5,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0 and b'Android Debug Bridge' in result.stdout + result.stderr:
                return str(path.resolve())
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None
