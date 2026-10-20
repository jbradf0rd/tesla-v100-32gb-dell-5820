#!/usr/bin/env python3
"""
Re-apply Dell BIOS settings from a saved `smbios-token-ctl --dump-tokens` snapshot.
For use after a CMOS reset puts the 5820's BIOS back to defaults.

  restore-bios-tokens.py <snapshot.txt>            dry run: list what differs (default)
  restore-bios-tokens.py <snapshot.txt> --apply    activate each setting that was ON
                                                   in the snapshot but is OFF now

Dell options are pairs/groups of on/off tokens (e.g. "Warnings and Errors (Prompt)" /
"(ContinueWarnings)"), so restoring = activating the tokens that were ON.
Status-only tokens (e.g. chassis door state) are skipped.
"""
import re, subprocess, sys

SKIP_IDS = {0x8000, 0x8002, 0x8003, 0xa000}   # chassis intrusion status/reset: read-only state

def parse(text):
    out = {}
    for b in text.split("=" * 80):
        m = re.search(r"Token:\s*(0x[0-9a-fA-F]+)\s*-\s*(.*)", b)
        v = re.search(r"value:\s*(.*)", b)
        if m and v:
            out[int(m.group(1), 16)] = (m.group(2).strip(), v.group(1).strip())
    return out

def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--apply"):
        sys.exit(__doc__)
    apply = len(sys.argv) == 3
    snap = parse(open(sys.argv[1], encoding="utf-8", errors="replace").read())
    cur = parse(subprocess.run(["smbios-token-ctl", "--dump-tokens"], capture_output=True,
                               text=True, errors="replace").stdout)
    if len(snap) < 300 or len(cur) < 300:
        sys.exit(f"STOP: snapshot has {len(snap)} tokens, current has {len(cur)}; expected ~338")
    todo = [t for t, (name, val) in sorted(snap.items())
            if val == "bool = true" and t not in SKIP_IDS
            and cur.get(t, ("", ""))[1] == "bool = false"]
    print(f"snapshot tokens: {len(snap)}   current tokens: {len(cur)}   to restore: {len(todo)}")
    for t in todo:
        print(f"  0x{t:04x}  {snap[t][0]}")
    if not todo:
        print("Current BIOS settings already match the snapshot.")
        return
    if not apply:
        print("DRY RUN - nothing changed. Re-run with --apply to restore these settings.")
        return
    failed = []
    for t in todo:
        r = subprocess.run(["smbios-token-ctl", f"--token-id=0x{t:04x}", "--activate"],
                           capture_output=True, text=True, errors="replace")
        ok = r.returncode == 0
        print(f"  activate 0x{t:04x}: {'OK' if ok else 'FAILED ' + r.stdout.strip()[-120:]}")
        if not ok:
            failed.append(t)
    cur2 = parse(subprocess.run(["smbios-token-ctl", "--dump-tokens"], capture_output=True,
                                text=True, errors="replace").stdout)
    still = [t for t in todo if cur2.get(t, ("", ""))[1] != "bool = true"]
    print(f"restored {len(todo) - len(still)}/{len(todo)}; not restored: "
          + (", ".join(f"0x{t:04x}" for t in still) or "none"))
    print("Settings take effect on the next reboot.")

if __name__ == "__main__":
    main()
