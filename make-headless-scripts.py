#!/usr/bin/env python3
"""
Build the headless (SSH-only) pass-2 and restore scripts from THIS machine's pass-1 dump.

  python3 make-headless-scripts.py rc-before.bin

rc-before.bin is the `dmpstore -s` file written by headless/startup-pass1.nsh to
\\EFI\\mmioh\\rc-before.bin on the EFI system partition.

All parsing and safety gates come from make-payload.py (name, GUID, attributes 0x07,
CRC32, length 114/115, layout fingerprint, MMIOH currently zero). If any gate fails,
nothing is written.

Writes, next to this script:
  headless/startup-pass2.nsh   enables MMIOH (bytes 0-1 -> 00 02, bytes 4-5 -> 04 00);
                               writes ONLY if a fresh dump is byte-identical to
                               rc-before.bin, and refuses to run a second time
  headless/restore.nsh         writes the ORIGINAL bytes from rc-before.bin back
"""
import importlib.util, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("make_payload", HERE / "make-payload.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

G = mp.GUID_STR

PASS2 = r"""@echo -off
# PASS 2 - enable MMIOH window. Writes ONLY if the variable is still byte-identical
# to the pass-1 dump (rc-before.bin), and never runs twice.
set OUT NONE
for %a in fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9
  if exist %a:\EFI\mmioh\MMIOH.TAG then
    set OUT %a:\EFI\mmioh
  endif
endfor
if %OUT% == NONE then
  reset
endif
if exist %OUT%\pass2-done.txt then
  echo PASS2 already ran - not writing again >a %OUT%\pass2-skipped.txt
  reset
endif
echo PASS2-START >>a %OUT%\pass2-log.txt
dmpstore -guid {G} -s %OUT%\rc-check.bin SocketCommonRcConfig
comp %OUT%\rc-check.bin %OUT%\rc-before.bin >a %OUT%\pass2-comp.txt
set CMPRES %lasterror%
echo comp-result %CMPRES% >>a %OUT%\pass2-log.txt
if %CMPRES% == 0x0 or %CMPRES% == 0 then
  echo WRITING >>a %OUT%\pass2-log.txt
  setvar SocketCommonRcConfig -guid {G} -bs -rt -nv =H{NEW}
  echo setvar-result %lasterror% >>a %OUT%\pass2-log.txt
  dmpstore -guid {G} SocketCommonRcConfig >a %OUT%\rc-after.txt
  dmpstore -guid {G} -s %OUT%\rc-after.bin SocketCommonRcConfig
  echo PASS2-DONE >a %OUT%\pass2-done.txt
else
  echo NOT WRITING - variable differs from pass-1 dump >>a %OUT%\pass2-log.txt
endif
reset
"""

RESTORE = r"""@echo -off
set OUT NONE
for %a in fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9
  if exist %a:\EFI\mmioh-restore\RESTORE.TAG then
    set OUT %a:\EFI\mmioh-restore
  endif
endfor
if %OUT% == NONE then
  reset
endif
# RESTORE - writes the ORIGINAL bytes of SocketCommonRcConfig back
# (MMIOH window zero, exactly as dumped by pass 1 before any change).
echo RESTORE-START >>a %OUT%\restore-log.txt
dmpstore -guid {G} -s %OUT%\rc-before-restore.bin SocketCommonRcConfig
setvar SocketCommonRcConfig -guid {G} -bs -rt -nv =H{ORIG}
echo setvar-result %lasterror% >>a %OUT%\restore-log.txt
dmpstore -guid {G} -s %OUT%\rc-after-restore.bin SocketCommonRcConfig
dmpstore -guid {G} SocketCommonRcConfig >a %OUT%\rc-after-restore.txt
echo RESTORE-DONE >>a %OUT%\restore-log.txt
reset
"""

def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    blob = pathlib.Path(sys.argv[1]).read_bytes()
    cur = mp.parse_dmpstore_save(blob)          # exits on any save-file problem
    if cur is None:
        sys.exit("REFUSING: input is not a dmpstore -s save file (use the pass-1 rc-before.bin)")
    n = len(cur)
    if n not in mp.OK_LENS:
        sys.exit(f"REFUSING: data is {n} bytes; known layouts are {mp.OK_LENS}")
    if not (cur[2:4] == b"\x00\x00" and cur[7] == 0x02 and cur[9] == 0x01):
        sys.exit("REFUSING: layout fingerprint mismatch; offsets of MmiohBase/MmiohSize cannot be trusted")
    if cur[0:2] != b"\x00\x00" or cur[4:6] != b"\x00\x00":
        sys.exit(f"REFUSING: MmiohBase/MmiohSize already non-zero ({mp.row(cur[0:2])} / {mp.row(cur[4:6])})")
    new = bytearray(cur)
    new[0:2] = b"\x00\x02"   # MmiohBase index 0x0200 = 512 GB
    new[4:6] = b"\x04\x00"   # MmiohSize index 4      = 256 GB
    assert [i for i in range(n) if cur[i] != new[i]] == [1, 4]
    out = HERE / "headless"
    (out / "startup-pass2.nsh").write_text(PASS2.replace("{G}", G).replace("{NEW}", new.hex()), newline="\n")
    (out / "restore.nsh").write_text(RESTORE.replace("{G}", G).replace("{ORIG}", cur.hex()), newline="\n")
    print(f"current  [0:16] : {mp.row(cur[:16])}")
    print(f"pass 2   [0:16] : {mp.row(new[:16])}")
    print(f"wrote {out / 'startup-pass2.nsh'}")
    print(f"wrote {out / 'restore.nsh'}")

if __name__ == "__main__":
    main()
