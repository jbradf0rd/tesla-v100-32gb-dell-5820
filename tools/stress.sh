#!/usr/bin/env bash
# V100 burn-in with thermal watchdog. Usage: stress.sh <seconds> <power_limit_W> <abort_temp_C>
DUR=${1:-600}; PL=${2:-200}; ABORT=${3:-84}
LOG=/home/opti/stress-$(date +%Y%m%d-%H%M%S).log
nvidia-smi -pl $PL >/dev/null && echo "power limit set to ${PL} W" | tee -a $LOG
cd /home/opti/gpu-burn && ./gpu_burn $DUR > $LOG.burn 2>&1 &
BURN=$!
echo "time     temp memT  power  sm_clk mem_clk util  hw_slow sw_therm pwr_cap | sysfans" | tee -a $LOG
MAXT=0; ABORTED=0
while kill -0 $BURN 2>/dev/null; do
  L=$(nvidia-smi --query-gpu=temperature.gpu,temperature.memory,power.draw,clocks.sm,clocks.mem,utilization.gpu,clocks_event_reasons.hw_slowdown,clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.sw_power_cap --format=csv,noheader,nounits)
  T=$(echo "$L" | cut -d, -f1 | tr -d " ")
  F=$(for f in /sys/class/hwmon/hwmon*/fan*_input; do printf "%s " $(cat $f); done)
  echo "$(date +%T) $L | $F" | tee -a $LOG
  [ "$T" -gt "$MAXT" ] && MAXT=$T
  if [ "$T" -ge "$ABORT" ]; then echo "ABORT: GPU reached ${T} C" | tee -a $LOG; pkill -f gpu_burn; ABORTED=1; break; fi
  sleep 5
done
wait $BURN 2>/dev/null
echo "max GPU temp: ${MAXT} C   aborted: ${ABORTED}" | tee -a $LOG
echo "--- gpu_burn result:" | tee -a $LOG; tail -4 $LOG.burn | tee -a $LOG
echo "--- Xid / NVRM errors during test:" | tee -a $LOG; journalctl -k --since "-$((DUR/60+2)) min" --no-pager | grep -Ei "xid|nvrm.*err" | tee -a $LOG || true
nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total,ecc.errors.corrected.volatile.total,retired_pages.pending --format=csv | tee -a $LOG
