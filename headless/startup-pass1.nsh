@echo -off
# PASS 1 - READ ONLY. Dumps SocketCommonRcConfig and all NVRAM variables, then resets.
# Nothing in this script writes to NVRAM.
set OUT NONE
for %a in fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9
  if exist %a:\EFI\mmioh\MMIOH.TAG then
    set OUT %a:\EFI\mmioh
  endif
endfor
if %OUT% == NONE then
  echo MMIOH.TAG not found - resetting without doing anything
  reset
endif
echo PASS1-START > %OUT%\pass1-started.txt
ver >a %OUT%\ver.txt
map -r >a %OUT%\map.txt
dmpstore -guid 4402ca38-808f-4279-bcec-5baf8d59092f >a %OUT%\guid-vars.txt
dmpstore -guid 4402ca38-808f-4279-bcec-5baf8d59092f SocketCommonRcConfig >a %OUT%\rc-before.txt
dmpstore -guid 4402ca38-808f-4279-bcec-5baf8d59092f -s %OUT%\rc-before.bin SocketCommonRcConfig
dmpstore -all >a %OUT%\all-vars.txt
echo PASS1-DONE >a %OUT%\pass1-done.txt
reset
