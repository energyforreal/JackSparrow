# Offline B: flat-hyp forward outcome stub

Economic replay tool skips `hold_at_synthesis` by design. Use:

1. [`counterfactual_replay_day0.md`](counterfactual_replay_day0.md) — promotion recommendation **hold_baseline_policy**
2. Feature dist of flat holds in [`offline_bc_analysis.json`](offline_bc_analysis.json)
3. When post-A produces more B4 events with `gates_passed_*`, extend with a dedicated hold-adoption CF (future tool work) before any live 3A.2

**Live flag:** remains false.
