#!/usr/bin/env python3
"""SMB access doctor — diagnose (and optionally fix) why a PC can't reach the HAP's
anonymous SMB1 share.

There are two *independent* questions, and people constantly conflate them:

1. **Will our own transfer work?** HAP Sync speaks SMB1 in user space via ``pysmb``, so it
   does NOT depend on any Windows SMB setting. ``probe_guest_share()`` is the authoritative
   test — if it connects, the transfer will work no matter what Windows is configured to do.

2. **Will the *native* Windows path work?** (File Explorer, mapped drives, Sony's "HAP Music
   Transfer".) Windows updates keep tightening SMB *client* defaults that the HAP's ancient
   Samba 3.0.37 can't satisfy — see docs/04-smb.md. The ``windows_*`` checks cover those.
   Fixing them edits system SMB security, so it needs admin (UAC).

The module is import-safe on every OS; Windows-only checks degrade to a 'na' finding elsewhere.
Nothing here imports tkinter or argparse — it is a pure engine shared by the GUI and the CLI.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

# Status values
OK, PROBLEM, WARN, NA = "ok", "problem", "warn", "na"
_GLYPH = {OK: "✓", PROBLEM: "✗", WARN: "!", NA: "·"}

# Hide the transient console window PowerShell/net would otherwise flash in a GUI build.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_LANMAN_PARAMS = r"HKLM:\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters"


@dataclass
class Finding:
    """One diagnostic result. ``fix_cmd`` is a PowerShell/cmd one-liner that remediates a
    PROBLEM (None when there is nothing to apply). ``native_only`` means the issue affects
    Explorer / HAP Music Transfer but NOT our pysmb-based transfer."""

    key: str
    title: str
    status: str
    detail: str = ""
    fix_cmd: str | None = None
    needs_admin: bool = False
    native_only: bool = False


# --------------------------------------------------------------------------- helpers

def _tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _ps(script: str, timeout: int = 20) -> tuple[int, str]:
    """Run a PowerShell snippet (no profile, non-interactive); return (rc, stdout-stripped).
    Returns (1, 'error: …') on any launch failure. Windows only — callers guard on IS_WINDOWS."""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
        )
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:  # noqa: BLE001 — a missing/blocked powershell must not crash the app
        return 1, f"error: {e}"


# --------------------------------------------------------------------------- probes

def probe_guest_share(host: str, timeout: int = 8) -> Finding:
    """Authoritative test: open the HAP's share anonymously over SMB1 exactly as the transfer
    does (pysmb, ports 445 then 139). Independent of every Windows SMB setting."""
    try:
        from smb.SMBConnection import SMBConnection
    except ImportError:
        return Finding("pysmb", "Transfer access (anonymous SMB1)", NA,
                       "pysmb not installed — run `pip install pysmb` to enable transfers.")
    last: Exception | None = None
    for direct, port in ((True, 445), (False, 139)):
        try:
            c = SMBConnection("", "", "hap-doctor", "HAP", use_ntlm_v2=False, is_direct_tcp=direct)
            if c.connect(host, port, timeout=timeout):
                shares: list[str] = []
                try:
                    shares = [s.name for s in c.listShares() if not s.isSpecial]
                except Exception:  # noqa: BLE001 — share enum is a bonus; connecting is the test
                    pass
                finally:
                    c.close()
                tail = f" Shares: {', '.join(shares)}." if shares else ""
                return Finding("pysmb", "Transfer access (anonymous SMB1)", OK,
                               f"Connected anonymously on port {port}.{tail} "
                               "Transfers will work regardless of Windows settings.")
        except Exception as e:  # noqa: BLE001
            last = e
    return Finding("pysmb", "Transfer access (anonymous SMB1)", PROBLEM,
                   f"Could not open an anonymous SMB1 session ({last}). "
                   "Make sure the HAP is awake (Wake) and on the same LAN.")


# --------------------------------------------------------------------------- Windows checks

def windows_smb_client() -> list[Finding]:
    """RequireSecuritySignature (must be False) and EnableInsecureGuestLogons (must be True),
    read as *effective* values from Get-SmbClientConfiguration. Reading needs no admin; the
    new 24H2/25H2 default lives in code, not the registry, so the cmdlet — not winreg — is
    authoritative here."""
    rc, out = _ps("Get-SmbClientConfiguration | "
                  "Select-Object RequireSecuritySignature,EnableInsecureGuestLogons | "
                  "ConvertTo-Json -Compress")
    sign = guest = None
    if rc == 0 and out:
        try:
            d = json.loads(out)
            sign = bool(d.get("RequireSecuritySignature"))
            guest = bool(d.get("EnableInsecureGuestLogons"))
        except (ValueError, AttributeError):
            pass

    out_findings: list[Finding] = []

    if sign is None:
        out_findings.append(Finding("signing", "SMB signing requirement", WARN,
                                    "Could not read the SMB client configuration.",
                                    native_only=True))
    elif sign:
        out_findings.append(Finding(
            "signing", "SMB signing is required — this blocks the HAP", PROBLEM,
            "Windows 11 24H2/25H2 turned this on by default; the HAP's Samba 3.0.37 can't "
            "sign, so Explorer is refused (often shown as a password prompt).",
            fix_cmd="Set-SmbClientConfiguration -RequireSecuritySignature $false -Force",
            needs_admin=True, native_only=True))
    else:
        out_findings.append(Finding("signing", "SMB signing not required", OK,
                                    "RequireSecuritySignature = False.", native_only=True))

    if guest is None:
        out_findings.append(Finding("guest", "Insecure guest logons", WARN,
                                    "Could not read the SMB client configuration.",
                                    native_only=True))
    elif not guest:
        out_findings.append(Finding(
            "guest", "Insecure guest logons are disabled", PROBLEM,
            "Explorer refuses the HAP's anonymous share with "
            "“security policies block unauthenticated guest access.”",
            fix_cmd=("Set-SmbClientConfiguration -EnableInsecureGuestLogons $true -Force; "
                     f"Set-ItemProperty '{_LANMAN_PARAMS}' AllowInsecureGuestAuth 1"),
            needs_admin=True, native_only=True))
    else:
        out_findings.append(Finding("guest", "Insecure guest logons enabled", OK,
                                    "EnableInsecureGuestLogons = True.", native_only=True))
    return out_findings


def windows_smb1_feature() -> Finding:
    """Is the SMB1 client present? Read the mrxsmb10 driver's Start value from the registry
    (4 = Disabled) — no admin, unlike Get-WindowsOptionalFeature which requires elevation."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\mrxsmb10") as k:
            start, _ = winreg.QueryValueEx(k, "Start")
    except FileNotFoundError:
        return Finding(
            "smb1", "SMB1 client feature is not installed", PROBLEM,
            "Explorer and HAP Music Transfer can't reach an SMB1-only device without it.",
            fix_cmd="Enable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol-Client -NoRestart",
            needs_admin=True, native_only=True)
    except OSError as e:
        return Finding("smb1", "SMB1 client feature", WARN,
                       f"Could not read the driver state ({e}).", native_only=True)
    if start == 4:  # SERVICE_DISABLED
        return Finding(
            "smb1", "SMB1 client is disabled", PROBLEM,
            "The mrxsmb10 driver start type is Disabled.",
            fix_cmd="Enable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol-Client -NoRestart",
            needs_admin=True, native_only=True)
    return Finding("smb1", "SMB1 client enabled", OK, "mrxsmb10 driver active.", native_only=True)


def windows_stale_mappings(host: str) -> Finding:
    """Find persistent mapped drives to the HAP that are genuinely broken — a stuck cached
    session forces a bogus credential prompt instead of a fresh guest logon. ``net use /delete``
    clears them and must run in the *user* (non-elevated) session, so this fix is not needs_admin.

    We do NOT trust ``Get-SmbMapping``'s Status field: a persistent mapping that is merely idle
    reports "Disconnected"/"Unavailable" yet reconnects fine on access. Flagging those would tell
    users to delete working drives. Instead we *actively* probe each HAP mapping with Test-Path —
    exactly what Explorer would experience — and flag only the ones that truly fail."""
    rc, out = _ps(
        "Get-SmbMapping | ForEach-Object { "
        "$p = if ($_.LocalPath) { $_.LocalPath + '\\' } else { $_.RemotePath }; "
        "[pscustomobject]@{ Local = $_.LocalPath; Remote = $_.RemotePath; "
        "Accessible = [bool](Test-Path -LiteralPath $p) } } | ConvertTo-Json -Compress",
        timeout=25)
    if rc != 0:
        return Finding("mappings", "Drive mappings", WARN,
                       "Could not enumerate mapped drives.", native_only=True)
    if not out:  # no mappings at all
        return Finding("mappings", "No stale drive mappings", OK, "", native_only=True)
    try:
        data = json.loads(out)
    except ValueError:
        return Finding("mappings", "Drive mappings", WARN,
                       "Could not parse mapped-drive list.", native_only=True)
    if isinstance(data, dict):
        data = [data]

    stale = [m for m in data
             if host in str(m.get("Remote", "")) and not m.get("Accessible")]
    if not stale:
        return Finding("mappings", "No stale drive mappings", OK,
                       "Mappings to the HAP are accessible (or none exist).", native_only=True)
    targets = [str(m.get("Local") or m.get("Remote")) for m in stale]
    fix = "; ".join(f'net use "{t}" /delete /y' for t in targets)
    return Finding(
        "mappings", f"Stale drive mapping(s): {', '.join(targets)}", PROBLEM,
        "A Disconnected/Unavailable mapped drive keeps forcing a password prompt. "
        "Clearing it lets Windows reconnect fresh as guest.",
        fix_cmd=fix, needs_admin=False, native_only=True)


# --------------------------------------------------------------------------- orchestration

def diagnose(host: str) -> list[Finding]:
    """Full diagnosis for ``host``. Reachability + the authoritative pysmb probe (cross-platform),
    then the Windows-native client checks where applicable."""
    findings: list[Finding] = []

    p445, p139 = _tcp_open(host, 445), _tcp_open(host, 139)
    if p445 or p139:
        findings.append(Finding("reach", "HAP reachable on the network", OK,
                                f"SMB port {'445' if p445 else '139'} open."))
        findings.append(probe_guest_share(host))
    else:
        findings.append(Finding(
            "reach", "HAP not reachable", PROBLEM,
            "No answer on ports 445/139. Is it awake (try Wake) and on the same LAN/subnet?"))

    if IS_WINDOWS:
        findings.extend(windows_smb_client())
        findings.append(windows_smb1_feature())
        findings.append(windows_stale_mappings(host))
    else:
        findings.append(Finding(
            "native", "Native-OS SMB checks skipped", NA,
            f"The Windows SMB-hardening checks/fixes don't apply on {sys.platform}."))
    return findings


def pending_fixes(findings: list[Finding]) -> list[Finding]:
    """The PROBLEM findings that actually have a remediation we can apply."""
    return [f for f in findings if f.status == PROBLEM and f.fix_cmd]


def summary(findings: list[Finding]) -> dict:
    """Quick rollup for callers: does the transfer work, and how many fixable native issues."""
    transfer = next((f for f in findings if f.key == "pysmb"), None)
    fixes = pending_fixes(findings)
    return {
        "transfer_ok": transfer is not None and transfer.status == OK,
        "problems": sum(1 for f in findings if f.status == PROBLEM),
        "fixable": len(fixes),
        "needs_admin": any(f.needs_admin for f in fixes),
    }


def format_report(findings: list[Finding]) -> list[str]:
    """Human-readable lines for a log pane or the console."""
    lines: list[str] = []
    for f in findings:
        scope = "  (native path only)" if f.native_only and f.status != OK else ""
        lines.append(f"{_GLYPH.get(f.status, '?')} {f.title}{scope}")
        if f.detail:
            lines.append(f"     {f.detail}")
        if f.status == PROBLEM and f.fix_cmd:
            tag = "fix (admin)" if f.needs_admin else "fix"
            lines.append(f"     {tag}: {f.fix_cmd}")
    return lines


# --------------------------------------------------------------------------- applying fixes

def _build_admin_script(admin_fixes: list[Finding]) -> str:
    body = ["$ErrorActionPreference = 'Continue'"]
    for f in admin_fixes:
        body.append(f"Write-Host '>> {f.title}'")
        body.append(f.fix_cmd or "")
    body.append("Write-Host 'Done. You can close this window.'")
    return "\r\n".join(body)


def apply_fixes(findings: list[Finding], on_log=None, wait: bool = True) -> tuple[bool, str]:
    """Apply every pending fix. Non-admin fixes (clearing stale mappings) run in the current
    user session — important, because an elevated process sees a *different* drive-letter
    namespace and wouldn't find the user's mappings. Admin fixes are bundled into one
    self-elevating PowerShell script so the user sees a single UAC prompt.

    Returns (changed, message). ``changed`` is True if at least one fix ran."""
    log = on_log or (lambda *_: None)
    if not IS_WINDOWS:
        return False, "Automatic fixing is Windows-only."
    fixes = pending_fixes(findings)
    if not fixes:
        return False, "Nothing to fix."

    changed = False
    non_admin = [f for f in fixes if not f.needs_admin]
    admin = [f for f in fixes if f.needs_admin]

    # 1) Non-admin fixes in the user context (stale mapped drives live here, not under UAC).
    for f in non_admin:
        log(f">> {f.title}")
        rc, out = _ps(f.fix_cmd, timeout=30)
        changed = True
        if rc != 0 and out:
            log(f"   (note: {out.splitlines()[0] if out else 'non-zero exit'})")

    # 2) Admin fixes via a single self-elevating PowerShell (one UAC prompt for all of them).
    if admin:
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".ps1", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(_build_admin_script(admin) + "\r\n")
            log(f">> Requesting admin to apply {len(admin)} system fix(es) (UAC)…")
            wait_flag = "-Wait " if wait else ""
            launcher = (
                "Start-Process powershell "
                f"-Verb RunAs {wait_flag}"
                f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"{path}\"'"
            )
            rc, out = _ps(launcher, timeout=300)
            if rc != 0:
                msg = "Elevation was declined or failed — system fixes were not applied."
                log(f"   {msg}")
                return changed, msg
            changed = True
        finally:
            try:
                if not wait:  # if we waited, the script has run and the temp file can go
                    pass
                else:
                    os.unlink(path)
            except OSError:
                pass

    return changed, ("Fixes applied. Reconnect to the HAP "
                     "(stale mappings were cleared; reopen \\\\<hap-ip>).")


# --------------------------------------------------------------------------- standalone CLI

def _main(argv: list[str]) -> int:
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(
        prog="smb_doctor",
        description="Diagnose (and optionally fix) SMB access to the HAP.")
    ap.add_argument("host", help="HAP IP address, e.g. 192.168.1.28")
    ap.add_argument("--fix", action="store_true",
                    help="apply the fixes for any problems found (Windows asks for admin)")
    args = ap.parse_args(argv[1:])

    findings = diagnose(args.host)
    print("\n".join(format_report(findings)))
    s = summary(findings)
    print()
    print("Transfer (our tool): " + ("WORKS" if s["transfer_ok"] else "NOT WORKING"))
    if s["fixable"]:
        print(f"{s['fixable']} fixable native-Windows issue(s) found"
              + (" (admin required)." if s["needs_admin"] else "."))
        if args.fix:
            changed, msg = apply_fixes(findings, on_log=print)
            print(msg)
            return 0 if changed else 1
        print("Re-run with --fix to apply them.")
    return 0 if s["transfer_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
