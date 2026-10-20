# NVIDIA Tesla V100 32 GB in a Dell Precision 5820 (BIOS 2.48): the MMIOH fix applied headless, over SSH

A Tesla V100 32 GB installed in a Dell Precision 5820 Tower stops the machine before POST completes: it power-cycles several times, then sits with a steady white power LED, moderate fan speed, and no operating system, even with "Memory Map IO above 4GB" enabled. The firmware ships with its high 64-bit MMIO window (MMIOH) set to zero size in the hidden NVRAM variable `SocketCommonRcConfig`, so the card's 32 GB BAR1 cannot be placed. Changing two bytes of that variable, with no BIOS flash, makes the machine POST and boot with the card installed. On BIOS 2.48 the variable is invisible to Linux, and this machine has no display adapter, so the fix was applied without a monitor, keyboard, or USB stick: the EDK2 UEFI Shell runs from the internal EFI system partition, launched once through `efibootmgr --bootnext` from an SSH session, and every script runs unattended and writes its output back to that partition for inspection from Linux. The same mechanism provided a tested restore path before any write took place.

Readers with a monitor and keyboard can apply the same edit from a USB-booted shell; that method is documented in [kaykavous-ai/tesla-p40-dell-precision-5820](https://github.com/kaykavous-ai/tesla-p40-dell-precision-5820), where it was confirmed on a 5820 with BIOS 2.41.

## The machine

| | |
|---|---|
| Workstation | Dell Precision 5820 Tower, BIOS **2.48.0** (11/05/2025), Xeon W-2135, board 0X8DXD |
| Memory | 64 GB DDR4-2666 ECC RDIMM (8 × 8 GB, all four channels) |
| Power supply | 950 W Dell unit with the factory GPU power leads |
| OS | Ubuntu 24.04.5 LTS, HWE kernel 7.0.0-38, booted UEFI, Secure Boot off |
| Card | NVIDIA GV100GL "Tesla PG500-216" (`10de:1df0`), a V100 SXM2 32 GB module on a PCIe adapter board, VBIOS 88.00.9C.00.01 |
| Card power | Dell GPU lead (8-pin + 6-pin) into a dual PCIe-to-EPS 8-pin adapter |
| Cooling | Blower fan on the card, powered from a 12 V source |
| Display | None. The Xeon W has no integrated graphics and the V100 has no outputs; the machine runs headless over SSH |

The drive in this workstation came from an OptiPlex 7070, so the hostname still names the old machine. `dmidecode` identifies the hardware correctly, which matters because the OptiPlex and the Precision have nothing in common where power, slots, and firmware are concerned.

## Symptom and diagnosis

With the V100 in SLOT2 or SLOT4, the machine powered on, cycled, and then held a steady white front LED with the rear PSU LED green and the fans at a moderate speed. It never reached the network, even after thirty minutes. Removing the card restored a normal boot.

The persistent systemd journal settled where the failure occurred. `journalctl --list-boots` showed no boot at all between the last good boot and the first boot after the card was removed, so every attempt with the V100 died in firmware before GRUB, and neither the kernel nor the NVIDIA driver was involved. `/proc/iomem` on the empty machine showed the second piece of evidence: each of the four CPU PCIe stacks received a 64-bit window of exactly 1 GiB (`380040000000-38007fffffff` for stack `0000:16`, and so on), and a 32 GB BAR cannot fit in a 1 GiB window.

Several commonly repeated suggestions do not apply to this failure. Intel VMD on this board owns only two x4 hot-plug ports (`/sys/bus/pci/slots/91` and `92`, the NVMe bays), never the x16 graphics slots. `pci=realloc` cannot enlarge a host-bridge window that the firmware reports as 1 GiB, and it proved unnecessary after the fix. "Primary Video Slot" and the CSM settings are irrelevant once the window exists.

## BIOS 2.48: what differs from 2.41

On BIOS 2.41 the variable was written from a USB-booted shell. On BIOS 2.48 the variable still exists and carries the attributes `NV+RT+BS` according to the shell's own `dmpstore`, yet it does not appear under `/sys/firmware/efi/efivars` at all, so Linux can neither read nor write it. The dump taken from the shell on this machine is byte-for-byte identical to the published 2.41 dump (SHA-256 `552f39c9…a7a1`, CRC32 `ac17942b`), so the 115-byte layout and the two-field edit carry over unchanged, and after the write this machine's dump matched the published 2.41 result byte for byte (SHA-256 `caa5e2ff…`). `rc-before.bin` and `rc-after.bin` in this repository are those two files, in `dmpstore -s` format.

## How the BIOS change was made from SSH

The firmware's own boot manager does the work that a person at the keyboard would otherwise do. Four properties of the platform make an unattended run possible. The EDK2 shell looks for `startup.nsh` in the directory it was launched from, so a shell placed in its own folder on the EFI system partition runs that folder's script and nothing else. `efibootmgr --create-only` adds a boot entry without placing it in `BootOrder`, so the shell can never start on an ordinary boot. `efibootmgr --bootnext` tells the firmware to use that entry for exactly one boot, after which the normal order resumes. The shell scripts locate their own filesystem by searching `fs0` through `fs9` for a marker file, write every result to that folder, and end with `reset`, so the machine returns to Ubuntu without intervention and the results can be read over SSH.

Each run is one command from SSH followed by a reboot of about a minute:

```
sudo efibootmgr -n 0001 && sudo reboot      # 0001 = the shell entry created below
```

The arrangement on this machine was two folders on the ESP, each with its own copy of `Shell.efi` and its own boot entry: `\EFI\mmioh\` (Boot0001, the read and the fix) and `\EFI\mmioh-restore\` (Boot0002, the self-test and the undo). Only one file named `startup.nsh` existed in each folder at any time, and none existed at the ESP root.

## Procedure

Every step except the last runs with the card removed, because the machine cannot POST with it installed until the fix is in place. Secure Boot must be off, since `Shell.efi` is unsigned.

1. **Stage the shell.** Download `Shell.efi` from EDK2 tag `edk2-stable201903` (`ShellBinPkg/UefiShell/X64/Shell.efi`, 938,880 bytes, SHA-256 `50437f8f0623a076f350ae937b0054f5912a14bbf9948c9665ca6ae4b0f31e7a`), confirm the checksum, find the ESP disk and partition with `findmnt /boot/efi`, and create the folder, marker, and boot entry:

   ```
   sudo mkdir -p /boot/efi/EFI/mmioh
   sudo cp Shell.efi /boot/efi/EFI/mmioh/
   sudo cp headless/startup-pass1.nsh /boot/efi/EFI/mmioh/startup.nsh
   echo marker | sudo tee /boot/efi/EFI/mmioh/MMIOH.TAG >/dev/null
   sudo efibootmgr -C -d /dev/sda -p 1 -L "MMIOH UEFI Shell" -l '\EFI\mmioh\Shell.efi'
   efibootmgr      # note the new BootNNNN; BootOrder must be unchanged
   ```

2. **Pass 1, read-only.** `sudo efibootmgr -n NNNN && sudo reboot`. The script dumps `SocketCommonRcConfig` to `rc-before.bin` and `rc-before.txt`, lists every NVRAM variable to `all-vars.txt`, records `ver` and `map -r`, and resets. It contains no `setvar`.

3. **Check the dump and build pass 2.** Copy `/boot/efi/EFI/mmioh/rc-before.bin` off the ESP and run `python3 make-headless-scripts.py rc-before.bin`. The generator imports `make-payload.py` and applies all of its gates (name, GUID, attributes `0x07`, CRC32, length 114 or 115, layout fingerprint, both fields currently zero), then writes `headless/startup-pass2.nsh` and `headless/restore.nsh` from this machine's own bytes. Pass 2 changes bytes 1 and 4 only: `00 00 00 00 00 00` becomes `00 02 00 00 04 00`, which sets MmiohBase to index `0x0200` (512 GB) and MmiohSize to index 4 (256 GB).

4. **Pass 2, the write.** Copy `headless/startup-pass2.nsh` to `/boot/efi/EFI/mmioh/startup.nsh`, then `sudo efibootmgr -n NNNN && sudo reboot`. The script takes a fresh dump, compares it with `rc-before.bin` using the shell's `comp`, and calls `setvar` only when the two are identical; it also refuses to run if `pass2-done.txt` already exists. Its log on this machine read `comp-result 0x0`, `WRITING`, `setvar-result 0x0`. Rename the script afterwards (`pass2.nsh.RAN`) so it cannot run again.

5. **Verify without the card.** Compare `rc-after.bin` with the expected bytes, then check the host-bridge windows. On this machine each CPU stack went from 1 GiB to 256 GiB:

   ```
   $ sudo grep -E "PCI Bus 0000:(00|16|64|b2)$" /proc/iomem | grep -vE "^ *[0-9a-f]{8}-"
   380000000000-383fffffffff : PCI Bus 0000:00
   384000000000-387fffffffff : PCI Bus 0000:16
   388000000000-38bfffffffff : PCI Bus 0000:64
   38c000000000-38ffffffffff : PCI Bus 0000:b2
   ```

6. **Install the card and wait.** Power off, fit the V100, power on, and leave the machine alone. It power-cycles about five times on every cold boot with the card present, then boots; Ubuntu was reachable within roughly two minutes. Never enter F2 Setup and save afterwards, because Setup rewrites its own copy of the variable with zeros.

## Safety precautions

The owner set the condition that no BIOS value would be typed by hand, so every change was scripted, gated, and verified, and the undo path was built and tested before the write. A snapshot of the machine's state went to `/root/failsafe-20261019` with SHA-256 sums, and a verified copy went to a second computer. It holds the original `SocketCommonRcConfig` dump, all 338 Dell BIOS tokens before and after the one deliberate token change, the full NVRAM variable listing, `efibootmgr -v`, `dmidecode`, `lspci -vvv`, `/proc/iomem`, the kernel command line, the GRUB defaults, the apt pin file, the package list, and a tarball of the entire ESP.

The restore entry (Boot0002) runs `headless/restore.nsh`, which writes the original bytes from pass 1 back. It covers every failure in which the machine still POSTs, with or without the card. It lives in its own folder, so its script can never be confused with the fix, and it was staged like this before pass 2:

```
sudo mkdir -p /boot/efi/EFI/mmioh-restore
sudo cp Shell.efi /boot/efi/EFI/mmioh-restore/
sudo cp /boot/efi/EFI/mmioh/rc-before.bin /boot/efi/EFI/mmioh-restore/rc-original.bin
echo marker | sudo tee /boot/efi/EFI/mmioh-restore/RESTORE.TAG >/dev/null
sudo cp headless/selftest.nsh /boot/efi/EFI/mmioh-restore/startup.nsh     # later: headless/restore.nsh
sudo efibootmgr -C -d /dev/sda -p 1 -L "MMIOH RESTORE" -l '\EFI\mmioh-restore\Shell.efi'
```

Before the write, the same entry ran `headless/selftest.nsh` twice in read-only form. The self-test proved that the shell finds a script in its own folder, that the folder search works, and that `comp` and the `if … or …` test branch correctly: identical files return `0x0` and take the equal branch, and different files return `0x1B` and take the other. Pass 2's guard depends on exactly that logic. The restore write itself has not been exercised, because the only safe way to test it would have been to write the original bytes over themselves.

If the machine ever fails to POST even with the card removed, the remaining path is a CMOS reset (the RTCRST jumper or the coin cell), which returns `SocketCommonRcConfig` to factory zero and resets the BIOS settings. `tools/restore-bios-tokens.py` then re-applies the saved token snapshot from Linux; it lists differences in a dry run by default and changes nothing without `--apply`. Settings that Linux cannot read through the token interface, such as VMD and Primary Video Slot, fall back to defaults, which suit headless use.

Several smaller precautions closed specific risks. A stray copy of the write script at the ESP root was deleted before the self-tests, so no shell could pick it up through its search path. Pass 2 stayed renamed (`pass2.nsh.DISARMED`) until the moment of use. The one deliberate BIOS token change was made before pass 2, following the rule from the 2.41 write-up to make all other BIOS changes first and write the variable last, and pass 2's comparison confirmed that the token change had left `SocketCommonRcConfig` untouched. Every step was preceded by a dry run, a simulation, or a read-only pass.

## BIOS settings from Linux

The Precision 5820 predates Dell's `dell-wmi-sysman` interface (`modprobe dell_wmi_sysman` returns "No such device"), but the older SMBIOS token interface works through the in-kernel `dell_smbios` and `dcdbas` drivers. Ubuntu's `smbios-utils` package provides `smbios-token-ctl`, which read 338 tokens on this machine. Its built-in `--dump-tokens-csv` export covered only 69 of them and omitted tokens that matter here, such as `0x0382 MmioAbove4Gb (Enable)` and the Warnings and Errors group, so the snapshot uses the full `--dump-tokens` text and `tools/restore-bios-tokens.py` parses that format.

The token dump also showed that "Warnings and Errors" was still set to Prompt, although it had been changed in Setup earlier without being saved. On a headless machine Prompt means POST can stop at a warning and wait for F1 on a screen nobody can see, so it was changed to Continue on Warnings, which still halts on real errors:

```
sudo smbios-token-ctl --token-id=0x044e --activate      # Warnings and Errors (ContinueWarnings)
```

A full diff of the before and after snapshots showed that change and nothing else, and it persisted across later reboots. No token was written after pass 2.

## Software installed and configured

The machine had the NVIDIA open kernel module (`nvidia-driver-580-open`) installed for an RTX 5060 that had been used for display. Blackwell cards require the open module and Volta cards require the proprietary one, so one driver cannot serve both, and the 5060 was removed for good. The driver was switched to `nvidia-driver-580` 580.178.04 from NVIDIA's CUDA apt repository, the source of the existing packages. The `-open` packages were removed and purged, and `nvidia-settings`, `nvidia-persistenced`, `nvidia-modprobe`, and `libxnvctrl0` were brought down from 615 to 580 so that the whole stack matched. DKMS built the module for kernels 7.0.0-34 and 7.0.0-38, and `modinfo nvidia` reports license `NVIDIA`.

The 580 branch is the last to support Volta, and the CUDA repository already offered 615, so `tools/nvidia-volta-pin` (installed as `/etc/apt/preferences.d/nvidia-volta-pin`) holds the line by version. It blocks the open-module packages entirely, prefers 580.x for every driver package at priority 1001 (which also allowed the downgrade), blocks driver branches 590 and later, and blocks the `cuda`, `cuda-toolkit`, and CUDA 13 metapackages. A pin by repository would have been simpler, but it would have orphaned the installed packages, which all came from that repository.

CUDA 12.8 and 12.9 were already installed and still compile for `sm_70`, with a deprecation warning; CUDA 13 cannot target Volta, even though `nvidia-smi` reports "CUDA Version: 13.0" as the driver's ceiling. PyTorch dropped Volta from its cu128 and cu129 wheels in 2.11, so this card needs the cu126 wheels, and 2.14 is the last release that ships them.

The remaining additions were `smbios-utils` for the BIOS tokens, the EDK2 `Shell.efi` on the ESP, and [`gpu-burn`](https://github.com/wilicc/gpu-burn) built with `make CUDAPATH=/usr/local/cuda-12.9 COMPUTE=70`. `tools/stress.sh` wraps `gpu-burn` with a thermal watchdog that logs temperature, power, clocks, slowdown flags, and system fan speeds every five seconds and kills the run if the GPU reaches a set temperature.

## Hardware notes

The V100's power socket takes an 8-pin CPU/EPS plug, so the Dell GPU lead feeds it through a dual PCIe-to-EPS adapter; a PCIe plug forced into that socket shorts 12 V to ground. The 950 W supply carries one V100 at 250 W with ample margin, and two cards plus the CPU come to roughly 720 W at peak. The front system fan must stay connected: with its header empty, the BIOS reports a fan failure and powers off, and "Continue on Warnings" does not override it. The optical-drive power lead in this chassis serves a slim drive and carries no 12 V, so a 12 V blower on it does not spin; the blower needs a full-size SATA power plug from the hard-drive lead or a fan header. One of the two blowers on hand also turned out to be dead. The first boot after the memory upgrade spent more than six minutes in memory training before the network came up.

## Results

| Check | Result |
|---|---|
| Enumeration | `0000:65:00.0` 3D controller `10de:1df0`, driver `nvidia` |
| BAR1 | `Region 1: Memory at 38b000000000 (64-bit, prefetchable) [size=32G]`; `nvidia-smi` BAR1 Total 32768 MiB |
| Link | Gen3 x16 (`LnkSta: Speed 8GT/s, Width x16`) |
| Memory health | ECC enabled; volatile and aggregate SBE/DBE 0; retired pages 0 |
| Thermal limits | max operating 83 °C, slowdown 88 °C, shutdown 91 °C |
| `gpu-burn`, 10 min at 200 W | GPU 0: OK, 0 errors, max 59 °C, about 11.2 TFLOPS FP32, no thermal slowdown, no Xid |
| `gpu-burn`, 10 min at 250 W | GPU 0: OK, 0 errors, max 66 °C, mean 242 W under load (peak 253 W), about 12.1 TFLOPS FP32, no hardware or thermal slowdown, no Xid |

## Gotchas

In the EDK2 shell, `>a` overwrites a file and `>>a` appends to it; the first self-test logged only its last line for that reason. The shell's `%lasterror%` reads `0x0` after an identical `comp` and `0x1B` after a mismatch. `efibootmgr -c` places a new entry at the front of `BootOrder`, so `-C` is the correct flag here. The shell's text output is ASCII when redirected with `>a`, and `iconv` should not be applied to it. Once, `systemctl poweroff` completed in the OS but left the hardware on, and the power button finished the job.

## Files

| File | Purpose |
|---|---|
| `headless/startup-pass1.nsh` | Read-only dump from the ESP; tested on this machine |
| `headless/selftest.nsh` | Read-only test of folder discovery and `comp` branching; tested |
| `make-headless-scripts.py` | Builds `headless/startup-pass2.nsh` and `headless/restore.nsh` from your own `rc-before.bin`, using the gates in `make-payload.py`; its output for this machine is identical to the pass 2 that ran |
| `tools/nvidia-volta-pin` | apt preferences file locking the driver to 580 and blocking the open module and CUDA 13 |
| `tools/restore-bios-tokens.py` | Re-applies Dell BIOS tokens from a `smbios-token-ctl --dump-tokens` snapshot; dry run by default |
| `tools/stress.sh` | `gpu-burn` wrapper with thermal watchdog: `stress.sh <seconds> <power_limit_W> <abort_temp_C>` |
| `make-payload.py` | Parser and safety gates for `SocketCommonRcConfig` dumps, from kaykavous-ai/tesla-p40-dell-precision-5820 (MIT), two messages made machine-neutral |
| `rc-before.bin`, `rc-after.bin` | The variable before and after the fix, in `dmpstore -s` format; byte-identical to this machine's dumps |

Never copy another machine's bytes into a `setvar` command. The generated scripts are excluded from the repository for that reason.

## Status

One V100 is installed and validated in SLOT2. The second card waits for a working blower; the 256 GB window on each stack leaves room for both, and the plan is SLOT4 with its own GPU lead and adapter.

## Credits and license

The root cause and the two-byte fix come from [xCuri0/ReBarUEFI discussion #331](https://github.com/xCuri0/ReBarUEFI/discussions/331), where it was found for a Tesla V100 in a Precision 7920, and from [kaykavous-ai/tesla-p40-dell-precision-5820](https://github.com/kaykavous-ai/tesla-p40-dell-precision-5820), which confirmed it on a 5820 with BIOS 2.41, documented the 115-byte layout, and supplied `make-payload.py` and the two dump files. The headless method, the restore kit, and the BIOS 2.48 findings were worked out by Joe Bradford with Claude Code (Anthropic), which ran the diagnostics and scripts over SSH while the owner did the physical work. MIT license; see `LICENSE`.
