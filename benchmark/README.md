# Benchmarking two Tesla V100 32 GB cards in a Dell Precision 5820: Phases 0 to 4

With both V100s POSTing and validated (see the [main README](../README.md)), the next question was which local inference engine and configuration makes the best use of them. A written protocol fixed the procedure in advance: Phase 0 builds a frozen measurement harness and a fixed workload, Phase 1 measures the cards with no inference engine, Phases 2 and 3 run two engines (Strata, a mixture-of-experts engine with expert offload to host RAM, and NInfer, a dense-model engine with tensor parallelism), and Phase 4 applies a scoring rule chosen before any result was seen. Phase 5, automated tuning of the winner, has not been run yet. Claude Code ran the whole protocol over SSH as orchestrator, with subagents doing the builds and the analysis, while the owner handled the hardware.

The result: **NInfer running Qwen3.8-27B (NVFP4) tensor-parallel across both cards wins**, at 110 tokens/s on short prompts and 103 tokens/s after an 80K-token prompt. Strata running the much larger Qwen3.8-Flash-Next MoE across both cards places third on the score but reads long prompts more than twice as fast. Every configuration passed every correctness check, and the runs uncovered a hardware defect worth knowing about: direct card-to-card (P2P) copies on this board are slow and corrupt data, while the driver reports P2P as available.

## The machine during the benchmark

| | |
|---|---|
| Workstation | Dell Precision 5820 Tower, BIOS 2.48.0, Xeon W-2135 (6 cores, 12 threads, one NUMA node), 64 GB DDR4-2666 ECC, 950 W PSU |
| GPUs | 2 × Tesla PG500-216 (V100 SXM2 32 GB on PCIe adapters), SLOT2 (`17:00.0`) and SLOT4 (`65:00.0`), Gen3 x16 each, 32 GB BAR1 each, topology `NODE`, no NVLink |
| Cooling | One blower per card, run at full speed from 12 V |
| Power limit | 250 W per card (stock), persistence mode on |
| Software | Ubuntu 24.04.5, kernel 7.0, driver 580.178.04 (proprietary, pinned), CUDA 12.8 for every build, NCCL 2.21.5 from the `nvidia-nccl-cu12` wheel (Ubuntu's NCCL has no Volta kernels) |
| Model disk | SATA SSD, 402 MB/s sequential read |

Adding the second card needed no BIOS change. The MMIOH window of 256 GB per PCIe stack holds both 32 GB BARs, and both cards came up with BAR1 32G, Gen3 x16 and zero ECC errors on the first boot.

## Phase 0: harness, workload and safety

**Harness.** `bench.py` reads a run spec (an engine profile plus a workload), starts the engine in its own process group, waits for its health endpoint, sends each fixture as a streaming OpenAI-style chat request (temperature 0, seed 42), and records per request the time to first token (TTFT), decode tokens/s (completion tokens minus one, divided by the time from first to last token), prefill tokens/s, GPU energy per token (from a 2 Hz `nvidia-smi` sampler) and peak host memory. A planted-value gate checks the long-document answers, and a parity check compares short-set outputs against the baseline for any profile documented as exact. `run.sh` reapplies the power limit, refuses to start while a `STOP` file exists, and runs the harness inside `systemd-run --user --scope -p MemoryMax=56G` so that a runaway engine cannot take the host down. The harness and the fixtures were then frozen: `freeze.sh` writes SHA-256 sums for both, and `bench.py` refuses to run if any file changed. A dry run against a dummy OpenAI-compatible server passed all 30 requests before any engine ran.

**Workload.** The short set holds 24 prompts of about 700 tokens, each generating 400 tokens: six English coding tasks, six English prose tasks, six tasks summarizing or translating passages of classical Arabic fiqh prose, and six Arabic question-and-answer tasks. The long set holds one document each at 32K, 80K and 128K tokens, in English and in Arabic. Each long document carries three random codes (`CODE-` plus 8 characters) planted at 10%, 50% and 90% depth, and its final question asks for all three, with a 256-token answer limit. The English documents come from Project Gutenberg (*The Adventures of Sherlock Holmes*, *Great Expectations*, *Moby Dick*). The Arabic ones are continuous stretches of three Hanbali works, rebuilt in page order from a local corpus with markup and page markers stripped: *Sharḥ Muntahā al-Irādāt* of al-Buhūtī for 128K, *Nayl al-Maʾārib* of al-Taghlibī for 80K, and the *Ḥāshiya* of al-Labadī on *Nayl al-Maʾārib* for 32K. The short Arabic passages come from other chapters of the same three books. Every stretch was sized with the Qwen3.8 tokenizer.

**Safety.** A watcher service samples both GPUs and host memory every 10 seconds, writes a status page, pushes phase changes and warnings to a phone through ntfy, and acts as the guard: a card at 84 °C for 30 seconds, power more than 25 W over the limit, any new uncorrectable ECC error, or less than 3 GiB of free host memory writes `STOP` and kills the running benchmark.

**Models.** Both models came from Hugging Face, were checksummed, staged on a NAS and copied to the machine over the LAN. The NInfer model needed care: the repository's `main` branch now holds a v3 artifact (magic `NINFER\0\x03`), which the V100 fork of NInfer rejects, so the v2 file was fetched by revision.

| Engine | Model | Source | Size |
|---|---|---|---|
| Strata | Qwen3.8-Flash-Next, MoE, IQ3_S GGUF | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`, revision `ed59f920` | 54.8 GB + 28.8 GB (two shards) |
| NInfer | Qwen3.8-27B, dense, NVFP4 | `neroued/Qwen3.8-27B-nvfp4-NInfer`, revision `3b84117e` (v2 artifact) | 21.5 GB |

**Engines.**

| Config | Engine | Repository and commit | Build |
|---|---|---|---|
| 2a | UnbiasedStrata, one card | `AIMDaAlien/UnbiasedStrata-V100`, branch `v100-pr1401`, `7833d96` | `cmake -DSTRATA_ENABLE_CUDA=ON -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_PORTABLE=ON -DSTRATA_EXPERIMENTAL_SM60=ON -DCMAKE_CUDA_ARCHITECTURES=70`, target `unbiased-strata`. The Makefile's `make build` hardcodes architectures 86, 89 and 120 and skips the SM60 flag, so it cannot be used for V100 |
| 2b | Strata, two cards with layer split | `jmnargi/Strata-V100`, `929a0e8` | per its `docs/NVIDIA_V100.md`, target `strata` |
| 3a, 3b | NInfer, one card and two cards (TP2) | `huangserva/ninfer-v100-tpx`, `9913bc2` | `cmake -G Ninja -DCMAKE_CUDA_ARCHITECTURES=70 -DNINFER_NCCL_ROOT=<nccl wheel>/nvidia/nccl -DBUILD_TESTING=OFF` |

Strata needs a "pack" of the dense weights and a multi-token-prediction draft head, neither of which is published. Both were built with upstream Strata's tools (`iq_pack.py` on the first GGUF shard, then `mtp_fetch.py`, `mtp_pack.py --experts q2_0` and `mtp_rt.py`); the two Strata forks share the format, so one pack (1.5 GB) and one draft head (787 MB) serve both. NInfer's two-card mode needs the weights split in two, which its `shard_qwen38_27b` tool did on the CPU (two shards of 12.4 GB, verified).

## Phase 1: the cards, with no inference engine

Both cards pass and match each other to within 1% on every measurement.

| Test | Card 0 (SLOT2) | Card 1 (SLOT4) |
|---|---|---|
| `gpu-burn`, 10 min alone | 12.22 TFLOPS, 0 errors, max 65 °C | 12.16 TFLOPS, 0 errors, max 64 °C |
| `gpu-burn`, 15 min both together | 12.22 TFLOPS, 0 errors, max 66 °C | 12.14 TFLOPS, 0 errors, max 64 °C |
| Sustained SM clock under burn | 1357 MHz, no throttling | 1357 MHz, no throttling |
| Median power under burn | 244 W | 242 W |
| HBM2 local read / write (`nvbandwidth`) | 1070 / 979 GB/s | 1070 / 983 GB/s |
| Device-to-device copy (`bandwidthTest`) | 951 GB/s | 951 GB/s |
| Host to card / card to host, pinned | 8.0 / 9.3 GB/s | 8.0 / 9.4 GB/s |

Running both cards at 250 W together for 15 minutes raised neither card more than 2 °C above its single-card temperature, and the 950 W supply held. ECC and PCIe replay counters were unchanged after all tests. Host memory (`sysbench`) ran at 26 GB/s.

Two findings matter for everything that follows.

**P2P between the two cards is broken.** `cudaDeviceCanAccessPeer` reports yes in both directions and `deviceQuery` lists peer access as available, but `p2pBandwidthLatencyTest` measures 0.46 GB/s bidirectional with P2P enabled against 11.5 GB/s with it disabled, with a P2P latency near 49 ms. Worse, `nvbandwidth`'s device-to-device read test aborted with "Invalid value when checking the pattern": the copy arrived with wrong data. The two cards sit on different CPU PCIe root ports, and on this platform the path between them does not carry peer traffic correctly. Every two-card configuration below therefore routes card-to-card traffic through host memory, and any engine that trusts the driver's P2P report must be told not to.

**Host-to-card bandwidth is about 8 GB/s,** where 11 to 13 GB/s is typical for Gen3 x16. Both links report Gen3 x16 before and after load, so this is a platform limit, not a downtrained link. It matters for Strata, which streams experts from host RAM.

## Phases 2 and 3: the engines

Each configuration ran a one-request smoke test, then its baseline profile twice on the quick workload (the short set plus the 32K documents) to measure run-to-run noise, then once on the full workload. The single-card configurations repeated the full run on the second card. Under protocol section 6.3, a difference counts only if it exceeds the noise margin: the larger of 2% and twice the median absolute difference between the two identical runs.

The baseline launch settings were:

| Config | Command (abridged) | Environment |
|---|---|---|
| 2a | `unbiased-strata --model <shard 1> --pack packs/iq3_s --mtp mtp --ctx 196608 --threads 12 -- --ple-io direct --resident-experts --kv int8 --kv-resident 32768 --spec 4 --vram-reserve-mib 2400 --adapt-async 1` | `OMP_NUM_THREADS=1 STRATA_SM70_TABLE=1 STRATA_ROUTE_TAIL_SKIP=0 STRATA_PREFILL_CPU_SHARE=0 STRATA_PREFILL_AUTO_MAX=32768` |
| 2b | `strata --serve --pack packs/iq3_s --native <shard 1> --expert-profile <...> --expert-cache auto --prefill auto --spec 4 --mtp mtp --max-context 196608 --kv int8 --pipeline-windows 2 --layer-split auto`, GPUs 0 and 1, through the fork's `serve/server.py` | `STRATA_PEER_NO_P2P=1` |
| 3a | `ninfer-serve qwen3_8_27b_nvfp4.ninfer --max-context 196608 --kv-capacity auto --max-concurrency 1 --prefill-chunk 2048 --kv-dtype int8 --spec mtp --draft-tokens 3 --lm-head-draft --seed 42` | |
| 3b | `tp2_proxy.py --gpus 0,1 --model-prefix <tp2 shards> --api-key-file <empty> --log-dir <run dir> -- --max-context 262144` plus the 3a engine flags | `NINFER_TP_NVLINK=0` |

Every request in every configuration also carried `chat_template_kwargs: {"enable_thinking": false}`.

### Full-workload results

Decode is tokens/s; TTFT is seconds to the first streamed token.

| Config | Short EN decode | Short AR decode | 32K decode / TTFT | 80K decode / TTFT | 128K decode / TTFT | Failed | Planted codes |
|---|---|---|---|---|---|---|---|
| 2a Strata, card 0 | 42.3 | 31.0 | 27.9 / 24.7 | 31.6 / 57.2 | 29.6 / 92.4 | 0 of 30 | 6 of 6 |
| 2a Strata, card 1 | 40.5 | 28.9 | 26.0 / 24.7 | 29.2 / 57.3 | 28.4 / 92.6 | 0 of 30 | 6 of 6 |
| 2b Strata, both cards | 78.7 | 42.7 | 53.1 / 15.3 | 52.7 / 33.0 | 52.8 / 52.4 | 0 of 30 | 6 of 6 |
| 3a NInfer, card 0 | 77.0 | 68.4 | 65.1 / 35.9 | 66.7 / 110.6 | 49.8 / 208.1 | 0 of 30 | 6 of 6 |
| 3a NInfer, card 1 | 76.9 | 68.4 | 65.1 / 35.9 | 66.6 / 110.5 | 49.7 / 207.8 | 0 of 30 | 6 of 6 |
| 3b NInfer, both cards (TP2) | 115.6 | 102.2 | 99.5 / 30.9 | 103.3 / 85.0 | 90.2 / 150.9 | 0 of 30 | 6 of 6 |

Across Phases 2 and 3, 394 requests ran without a single failure, and all 52 long-document answers returned all three planted codes.

**Strata (Phase 2).** Single-card Strata pins 38 GiB of experts in host RAM and peaks at 47 GiB of host memory. It is not repeatable from run to run, because `--adapt-async 1` is documented as not bit-exact: 22 of 24 short answers differed in wording between the two identical runs, and its per-request decode noise margin is about 9%. Card 1 ran 4 to 8% slower than card 0 in most groups, within that margin; the lower draft acceptance on card 1's long requests (0.44 against 0.54 at 80K) accounts for it, and the two cards ran at the same clock and power. The layer split across both cards nearly doubles decode speed and cuts TTFT by 40%, gives identical text on every repeat, and pins the most host memory of any configuration: 53.9 GiB at peak, 2 GiB under the 56 GiB cap. Its engine warned that `--pipeline-windows 2` on a two-stage split without the draft layer on the first card has lost to the serial loop on other hardware, which is a lead for tuning.

**NInfer (Phase 3).** NInfer holds the whole 27B model on the GPU and uses little host memory (12 GiB for one card, 22 GiB for two). Both NInfer configurations are deterministic: the repeat runs reproduced all 24 short answers token for token, so their noise margin sits at the 2% floor, and the parity check passed 24 of 24 on every comparison run. One card generates about as fast as Strata on two, and much faster on Arabic text (68 against 43 tokens/s), but its prefill is slow: 208 seconds before the first token of a 128K prompt. Tensor parallelism across both cards adds 50% to decode speed and cuts long-prompt TTFT by about a quarter, with about 0.7 seconds of fixed overhead per request in the proxy.

## Problems found and how they were resolved

1. **Thinking mode.** Qwen3.8 thinks before answering by default, and the harness's planted-value gate reads only the answer, not the reasoning. With a 256-token limit on the long documents, a thinking model would spend the whole budget reasoning and never answer. All three engines accept the standard `chat_template_kwargs.enable_thinking=false` request field, so every profile sends it. The alternative, thinking on with larger output limits, would have required new fixtures after the freeze.

2. **Strata two-card P2P.** The jmnargi fork enables peer access whenever the driver allows it, and it runs only a small test copy, which may pass on a path that corrupts larger transfers. `STRATA_PEER_NO_P2P=1` forces its host-memory route. The engine then measured the link at 7.9 GB/s and placed its layer split accordingly.

3. **NInfer single-card context.** At the protocol's `--max-context 262144`, NInfer refused to start on one card: "minimum Engine runtime reservation requires 11836962816 bytes in addition to 1073741824 bytes of automatic headroom, but only 12586771456 bytes are available after weights", 0.3 GB short. At 196,608 tokens, the same context as Strata, it starts with 3.4 GiB to spare and still covers the 128K documents. The two-card configuration kept 262,144, since each card holds only half the weights.

4. **NInfer two-card startup crash.** The TP2 ranks crashed on every start with `cudaErrorLaunchFailure: unspecified launch failure` at `tp2_comm.cpp:229`, and the proxy restarted them six times before the health check gave up. Line 229 sits in the self-test of the fork's NVLink inbox, a fast path in which each rank maps the other card's memory through CUDA IPC and writes into it directly. The fork enables it whenever peer access is reported, and it is meant for NVLink machines. Here it ran over the broken P2P path and faulted. `NINFER_TP_NVLINK=0` disables only the inbox and keeps the host shared-memory mailbox, and the ranks then reported "mailbox on, nvlink off" and ran without a lockstep failure.

5. **NInfer two-card housekeeping.** The proxy does not create its log directory and fails with `FileNotFoundError` when it is missing, so its logs now go into the run directory, which always exists. It requires `--api-key-file`, and an empty key file disables authentication on the ranks, which the harness needs, since it sends no bearer token. When the harness stopped the proxy, the two `ninfer-serve` ranks survived and held 12 GB on each card, so the batch driver now kills leftover ranks after every run. Stale `ninfer_tp2_lockstep*` files in `/dev/shm` should be cleared between sessions.

6. **Cooling.** Partway through setup, opti was briefly powered on with the GPU blowers disconnected. At idle, about 25 to 37 W per card, the passive V100 heatsinks climbed from 40 °C to 74 °C in twenty minutes, about 1 to 2 °C per minute, with no sign of levelling off, and the machine was shut down. Idle power rose with temperature as it went. A V100 without a blower is not safe even at idle. With the blowers running, the same cards idle at 31 to 35 °C and peak at 66 °C under 250 W of `gpu-burn`.

7. **CPU heat during builds.** Compiling three CUDA engines at once with unlimited parallel jobs drove the CPU package to 91 °C. Capping each build at three jobs brought it down to about 80 °C.

8. **UGREEN NAS rsync.** The NAS's rsync rejected every path with "invalid path", so the models were streamed over SSH with `cat` at about 115 MB/s, resumed by byte offset after an interruption, and checksummed on arrival.

## Phase 4: the winner

The rule was fixed in the protocol before any engine ran. A configuration is disqualified if it fails a planted-value gate or more than 1 request in 100. The score is the median of two numbers: the median decode speed over the whole short set (English and Arabic together), and the median decode speed after the 80K prompts. If two scores fall within the noise margin, the lower 80K TTFT wins. A fallback rule, recorded for long-document work, uses 128K decode in place of the short set.

| Config | Short-set decode | 80K decode | Score | 128K decode | Fallback score | 80K TTFT |
|---|---|---|---|---|---|---|
| **3b NInfer, both cards** | 110.1 | 103.3 | **106.7** | 90.2 | **96.7** | 85.0 s |
| 3a NInfer, card 0 | 75.2 | 66.7 | 71.0 | 49.8 | 58.3 | 110.6 s |
| 3a NInfer, card 1 | 75.2 | 66.7 | 70.9 | 49.7 | 58.2 | 110.5 s |
| 2b Strata, both cards | 69.5 | 52.7 | 61.1 | 52.8 | 52.7 | 33.0 s |
| 2a Strata, card 0 | 36.8 | 31.6 | 34.2 | 29.6 | 30.6 | 57.2 s |
| 2a Strata, card 1 | 36.6 | 29.2 | 32.9 | 28.4 | 28.8 | 57.3 s |

Nothing was disqualified. Two-card NInfer wins under both rules by a wide margin (40% above the runner-up on the main score, 50% on the fallback). Single-card NInfer is the runner-up. Its two cards tie within noise, and the tie-break picked card 1 by 0.2 seconds of TTFT, which is not a meaningful difference.

The score measures generation speed, and several things it does not measure bear on the choice.

**Waiting for a long prompt.** Strata on two cards reads an 80K prompt in 33 seconds; the winner takes 85 and single-card NInfer 111. At 128K the figures are 52, 151 and 208 seconds. The long answers here run 98 to 183 tokens, which take one to two seconds to generate at these speeds, so for a long document with a short answer the wait is almost all prefill, and Strata two-card is the fastest end to end.

**Different models.** The engines do not run the same model. Strata runs the large Qwen3.8-Flash-Next mixture-of-experts quantized to about 3.4 bits per weight, with most experts in host RAM. NInfer runs the dense Qwen3.8-27B in NVFP4, entirely on the GPUs. The benchmark measured speed, long-context retrieval of the planted codes (where all configurations scored perfectly) and repeatability. It did not measure answer quality, since the optional task check with reference answers was left empty, so whether the 27B dense model answers as well as the MoE remains untested here.

**Resources.** The winner occupies both cards. Single-card NInfer leaves the second card free at two thirds of the winner's speed. Strata two-card needs nearly all of the host's RAM. GPU energy per generated token on the short set runs from 3.5 J (Strata two-card) to 4.2 J (NInfer two-card); on an 80K request, the slow prefill makes NInfer cost about three times as much energy per answer as Strata.

## Status and next step

Phases 0 to 4 are complete, with every result committed in the benchmark repository on the machine. Phase 5 runs automated tuning on one configuration: a proposer suggests one change at a time from a fixed search space, and each change is screened and then confirmed in alternating A/B runs against the current best. It is capped at 60 trials or 12 hours. The candidates are the winner (NInfer TP2), the runner-up (single-card NInfer), or Strata two-card if long-document latency matters more than generation speed. Whichever runs, the P2P findings above stay in force: card-to-card traffic through host memory only.

## Credits

The protocol, harness and fixtures were written for this machine. The engines are the work of their authors: [AIMDaAlien/UnbiasedStrata-V100](https://github.com/AIMDaAlien/UnbiasedStrata-V100), [jmnargi/Strata-V100](https://github.com/jmnargi/Strata-V100) and [huangserva/ninfer-v100-tpx](https://github.com/huangserva/ninfer-v100-tpx), with the models from [ISTA-DASLab](https://huggingface.co/ISTA-DASLab) and [neroued](https://huggingface.co/neroued). The benchmark was run by Joe Bradford with Claude Code (Anthropic), which orchestrated the phases and delegated the builds and the analysis to subagents over SSH, while the owner did the physical work.
