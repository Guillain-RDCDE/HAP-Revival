"""The SMB access doctor, without Windows and without a HAP.

The engine's logic — what counts as fixable, how the report reads, how the
rollup is computed, how PowerShell output is parsed — is pure and testable
anywhere. PowerShell itself is replaced by a fake `_ps`; the TCP probe and the
pysmb session by stubs.
"""

import json

import pytest

import smb_doctor
from smb_doctor import NA, OK, PROBLEM, WARN, Finding


def test_pending_fixes_and_summary():
    findings = [
        Finding("reach", "reachable", OK),
        Finding("pysmb", "transfer", OK),
        Finding("signing", "signing required", PROBLEM, fix_cmd="Set-X", needs_admin=True),
        Finding("mappings", "stale", PROBLEM, fix_cmd="net use", needs_admin=False),
        Finding("other", "unfixable", PROBLEM),
        Finding("native", "skipped", NA),
    ]
    fixes = smb_doctor.pending_fixes(findings)
    assert [f.key for f in fixes] == ["signing", "mappings"]
    assert smb_doctor.summary(findings) == {
        "transfer_ok": True, "problems": 3, "fixable": 2, "needs_admin": True}
    assert smb_doctor.summary([])["transfer_ok"] is False


def test_format_report_shows_glyphs_scope_and_fix_commands():
    lines = smb_doctor.format_report([
        Finding("pysmb", "Transfer access", OK, "Connected."),
        Finding("signing", "Signing required", PROBLEM, "Blocks Explorer.",
                fix_cmd="Set-SmbClientConfiguration", needs_admin=True, native_only=True),
        Finding("mappings", "Stale mapping", PROBLEM, fix_cmd="net use x: /delete"),
        Finding("x", "Unknown status", "weird"),
    ])
    assert lines[0] == "✓ Transfer access"
    assert lines[1] == "     Connected."
    assert lines[2] == "✗ Signing required  (native path only)"
    assert "fix (admin): Set-SmbClientConfiguration" in lines[4]
    assert "     fix: net use x: /delete" in lines
    assert lines[-1].startswith("? Unknown status")


def test_probe_guest_share_without_pysmb(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "smb", None)
    monkeypatch.setitem(sys.modules, "smb.SMBConnection", None)
    finding = smb_doctor.probe_guest_share("1.2.3.4")
    assert finding.status == NA and "pip install pysmb" in finding.detail


class FakeSmbModule:
    """A stand-in for smb.SMBConnection whose behaviour each test chooses."""

    def __init__(self, connects, shares=(), raise_on_connect=None):
        self.connects = connects
        self.shares = shares
        self.raise_on_connect = raise_on_connect
        self.ports = []

    def __call__(self, *args, **kwargs):
        return self

    def connect(self, host, port, timeout=0):
        self.ports.append(port)
        if self.raise_on_connect:
            raise self.raise_on_connect
        return self.connects

    def listShares(self):
        class Share:
            def __init__(self, name, special):
                self.name, self.isSpecial = name, special

        return [Share(n, False) for n in self.shares] + [Share("IPC$", True)]

    def close(self):
        pass


def _install_fake_smb(monkeypatch, fake):
    import sys
    import types

    pkg = types.ModuleType("smb")
    mod = types.ModuleType("smb.SMBConnection")
    mod.SMBConnection = fake
    pkg.SMBConnection = mod
    monkeypatch.setitem(sys.modules, "smb", pkg)
    monkeypatch.setitem(sys.modules, "smb.SMBConnection", mod)


def test_probe_guest_share_reports_the_port_and_the_shares(monkeypatch):
    fake = FakeSmbModule(connects=True, shares=("HAP_Internal", "HAP_External"))
    _install_fake_smb(monkeypatch, fake)
    finding = smb_doctor.probe_guest_share("1.2.3.4")
    assert finding.status == OK
    assert "port 445" in finding.detail and "HAP_Internal, HAP_External" in finding.detail
    assert fake.ports == [445], "the first transport that answers wins"


def test_probe_guest_share_falls_back_to_netbios_then_fails(monkeypatch):
    fake = FakeSmbModule(connects=False, raise_on_connect=OSError("refused"))
    _install_fake_smb(monkeypatch, fake)
    finding = smb_doctor.probe_guest_share("1.2.3.4")
    assert finding.status == PROBLEM and "refused" in finding.detail
    assert fake.ports == [445, 139]


def test_diagnose_off_windows_skips_native_checks(monkeypatch):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", False)
    monkeypatch.setattr(smb_doctor, "tcp_port_open", lambda host, port, timeout=3.0: port == 139)
    monkeypatch.setattr(smb_doctor, "probe_guest_share",
                        lambda host: Finding("pysmb", "transfer", OK))
    keys = [f.key for f in smb_doctor.diagnose("1.2.3.4")]
    assert keys == ["reach", "pysmb", "native"]
    findings = smb_doctor.diagnose("1.2.3.4")
    assert "port 139" in findings[0].detail and findings[2].status == NA


def test_diagnose_unreachable_player(monkeypatch):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", False)
    monkeypatch.setattr(smb_doctor, "tcp_port_open", lambda host, port, timeout=3.0: False)
    findings = smb_doctor.diagnose("1.2.3.4")
    assert findings[0].key == "reach" and findings[0].status == PROBLEM
    assert "pysmb" not in [f.key for f in findings], "no point probing a dead host"


def test_diagnose_on_windows_runs_every_native_check(monkeypatch):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", True)
    monkeypatch.setattr(smb_doctor, "tcp_port_open", lambda host, port, timeout=3.0: True)
    monkeypatch.setattr(smb_doctor, "probe_guest_share",
                        lambda host: Finding("pysmb", "transfer", OK))
    monkeypatch.setattr(smb_doctor, "windows_smb_client",
                        lambda: [Finding("signing", "s", OK), Finding("guest", "g", OK)])
    monkeypatch.setattr(smb_doctor, "windows_smb1_feature", lambda: Finding("smb1", "f", OK))
    monkeypatch.setattr(smb_doctor, "windows_stale_mappings",
                        lambda host: Finding("mappings", "m", OK))
    keys = [f.key for f in smb_doctor.diagnose("1.2.3.4")]
    assert keys == ["reach", "pysmb", "signing", "guest", "smb1", "mappings"]


# ---------- the Windows checks, with PowerShell faked ----------


def test_windows_smb_client_reads_effective_values(monkeypatch):
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (
        0, json.dumps({"RequireSecuritySignature": True, "EnableInsecureGuestLogons": False})))
    sign, guest = smb_doctor.windows_smb_client()
    assert sign.status == PROBLEM and "RequireSecuritySignature $false" in sign.fix_cmd
    assert guest.status == PROBLEM and "AllowInsecureGuestAuth 1" in guest.fix_cmd
    assert sign.needs_admin and guest.native_only

    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (
        0, json.dumps({"RequireSecuritySignature": False, "EnableInsecureGuestLogons": True})))
    sign, guest = smb_doctor.windows_smb_client()
    assert sign.status == OK and guest.status == OK


def test_windows_smb_client_warns_when_powershell_fails(monkeypatch):
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (1, "error: no powershell"))
    sign, guest = smb_doctor.windows_smb_client()
    assert sign.status == WARN and guest.status == WARN
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (0, "not json"))
    assert smb_doctor.windows_smb_client()[0].status == WARN


def test_windows_stale_mappings_flags_only_broken_ones(monkeypatch):
    mappings = [
        {"Local": "H:", "Remote": "\\\\1.2.3.4\\HAP_Internal", "Accessible": False},
        {"Local": "I:", "Remote": "\\\\1.2.3.4\\HAP_External", "Accessible": True},
        {"Local": "Z:", "Remote": "\\\\other\\share", "Accessible": False},
    ]
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (0, json.dumps(mappings)))
    finding = smb_doctor.windows_stale_mappings("1.2.3.4")
    assert finding.status == PROBLEM and "H:" in finding.title and "I:" not in finding.title
    assert finding.fix_cmd == 'net use "H:" /delete /y'
    assert not finding.needs_admin, "net use must run in the user's own session"

    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (0, json.dumps(mappings[1])))
    assert smb_doctor.windows_stale_mappings("1.2.3.4").status == OK, "a single object is fine"
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (0, ""))
    assert smb_doctor.windows_stale_mappings("1.2.3.4").status == OK
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (1, ""))
    assert smb_doctor.windows_stale_mappings("1.2.3.4").status == WARN
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (0, "{bad"))
    assert smb_doctor.windows_stale_mappings("1.2.3.4").status == WARN


def test_windows_smb1_feature_reads_the_driver_start_value(monkeypatch):
    import sys
    import types

    class FakeWinreg:
        HKEY_LOCAL_MACHINE = 0
        start = 2

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def OpenKey(self, root, path):
            if self.start is None:
                raise FileNotFoundError
            if self.start == "boom":
                raise OSError("locked")
            return self._Key()

        def QueryValueEx(self, key, name):
            return self.start, 4

    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", types.ModuleType("winreg"))
    sys.modules["winreg"].HKEY_LOCAL_MACHINE = 0
    sys.modules["winreg"].OpenKey = fake.OpenKey
    sys.modules["winreg"].QueryValueEx = fake.QueryValueEx

    assert smb_doctor.windows_smb1_feature().status == OK
    fake.start = 4
    disabled = smb_doctor.windows_smb1_feature()
    assert disabled.status == PROBLEM and "SMB1Protocol-Client" in disabled.fix_cmd
    fake.start = None
    assert smb_doctor.windows_smb1_feature().status == PROBLEM
    fake.start = "boom"
    assert smb_doctor.windows_smb1_feature().status == WARN


def test_ps_survives_a_missing_powershell(monkeypatch):
    def no_such(*a, **k):
        raise FileNotFoundError("powershell")

    monkeypatch.setattr(smb_doctor.subprocess, "run", no_such)
    rc, out = smb_doctor._ps("Get-Date")
    assert rc == 1 and out.startswith("error:")


# ---------- applying fixes ----------


def test_apply_fixes_refuses_off_windows(monkeypatch):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", False)
    assert smb_doctor.apply_fixes([Finding("x", "x", PROBLEM, fix_cmd="y")]) == (
        False, "Automatic fixing is Windows-only.")


def test_apply_fixes_runs_user_fixes_then_one_elevated_script(monkeypatch, tmp_path):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", True)
    import os

    script = tmp_path / "fix.ps1"
    monkeypatch.setattr(smb_doctor.tempfile, "mkstemp", lambda suffix, text: (
        os.open(str(script), os.O_RDWR | os.O_CREAT), str(script)))
    ran = []
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: ran.append(script) or (0, ""))
    log = []
    findings = [
        Finding("mappings", "Stale mapping", PROBLEM, fix_cmd='net use "H:" /delete /y'),
        Finding("signing", "Signing", PROBLEM, fix_cmd="Set-A", needs_admin=True),
        Finding("guest", "Guest", PROBLEM, fix_cmd="Set-B", needs_admin=True),
        Finding("ok", "fine", OK),
    ]
    changed, msg = smb_doctor.apply_fixes(findings, on_log=log.append)
    assert changed and "Fixes applied" in msg
    assert ran[0] == 'net use "H:" /delete /y', "user-session fix first, un-elevated"
    assert ran[1].startswith("Start-Process powershell -Verb RunAs -Wait ")
    assert any("UAC" in line for line in log)
    assert not (tmp_path / "fix.ps1").exists(), "the script is removed after -Wait"


def test_apply_fixes_reports_a_declined_uac(monkeypatch, tmp_path):
    monkeypatch.setattr(smb_doctor, "IS_WINDOWS", True)
    monkeypatch.setattr(smb_doctor, "_ps", lambda script, timeout=20: (1, "declined"))
    findings = [Finding("signing", "Signing", PROBLEM, fix_cmd="Set-A", needs_admin=True)]
    changed, msg = smb_doctor.apply_fixes(findings, wait=False)
    assert not changed and "declined" in msg
    assert smb_doctor.apply_fixes([Finding("ok", "fine", OK)]) == (False, "Nothing to fix.")


def test_admin_script_and_launcher_shape():
    script = smb_doctor._build_admin_script([
        Finding("a", "Fix A", PROBLEM, fix_cmd="Set-A"),
        Finding("b", "Fix B", PROBLEM, fix_cmd="Set-B"),
    ])
    assert script.split("\r\n") == [
        "$ErrorActionPreference = 'Continue'",
        "Write-Host '>> Fix A'", "Set-A",
        "Write-Host '>> Fix B'", "Set-B",
        "Write-Host 'Done. You can close this window.'",
    ]
    launcher = smb_doctor._elevation_launcher(r"C:\t\fix.ps1", wait=False)
    assert "-Verb RunAs -ArgumentList" in launcher and r'"C:\t\fix.ps1"' in launcher
    assert "-Wait" in smb_doctor._elevation_launcher("x", wait=True)


# ---------- CLI ----------


def test_main_prints_the_report_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(smb_doctor, "diagnose", lambda host: [
        Finding("pysmb", "transfer", OK),
        Finding("signing", "Signing", PROBLEM, fix_cmd="Set-A", needs_admin=True),
    ])
    assert smb_doctor.main(["1.2.3.4"]) == 0
    out = capsys.readouterr().out
    assert "Transfer (our tool): WORKS" in out and "Re-run with --fix" in out

    applied = []
    monkeypatch.setattr(smb_doctor, "apply_fixes",
                        lambda findings, on_log=None: applied.append(1) or (True, "done"))
    assert smb_doctor.main(["1.2.3.4", "--fix"]) == 0 and applied

    monkeypatch.setattr(smb_doctor, "diagnose", lambda host: [Finding("reach", "dead", PROBLEM)])
    assert smb_doctor.main(["1.2.3.4"]) == 1
    assert "NOT WORKING" in capsys.readouterr().out


@pytest.mark.parametrize("status", [OK, PROBLEM, WARN, NA])
def test_every_status_has_a_glyph(status):
    assert status in smb_doctor._GLYPH
