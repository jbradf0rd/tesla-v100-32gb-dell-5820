@echo -off
set OUT NONE
for %a in fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9
  if exist %a:\EFI\mmioh-restore\RESTORE.TAG then
    set OUT %a:\EFI\mmioh-restore
  endif
endfor
if %OUT% == NONE then
  reset
endif
# SELF-TEST - READ ONLY. No setvar in this script.
echo SELFTEST-START >>a %OUT%\selftest-log.txt
dmpstore -guid 4402ca38-808f-4279-bcec-5baf8d59092f -s %OUT%\rc-now.bin SocketCommonRcConfig
dmpstore -guid 4402ca38-808f-4279-bcec-5baf8d59092f SocketCommonRcConfig >a %OUT%\rc-now.txt
comp %OUT%\rc-now.bin %OUT%\rc-original.bin >a %OUT%\comp-same.txt
set R1 %lasterror%
comp %OUT%\RESTORE.TAG %OUT%\rc-original.bin >a %OUT%\comp-diff.txt
set R2 %lasterror%
echo same-result %R1% >>a %OUT%\selftest-log.txt
echo diff-result %R2% >>a %OUT%\selftest-log.txt
if %R1% == 0x0 or %R1% == 0 then
  echo R1-EQUAL-BRANCH >>a %OUT%\selftest-log.txt
else
  echo R1-DIFFERENT-BRANCH >>a %OUT%\selftest-log.txt
endif
if %R2% == 0x0 or %R2% == 0 then
  echo R2-EQUAL-BRANCH >>a %OUT%\selftest-log.txt
else
  echo R2-DIFFERENT-BRANCH >>a %OUT%\selftest-log.txt
endif
echo SELFTEST-DONE >>a %OUT%\selftest-log.txt
reset
