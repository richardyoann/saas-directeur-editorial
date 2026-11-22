# Synthetic 75 second video check

The synthetic 75 second FFmpeg acceptance check is covered by the local CI
gate `video_75`. The GitHub workflow is retained as a manual diagnostic only;
it no longer starts a hosted runner for pull requests.

## Qualification evidence

- Candidate: PR #214, `a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9`.
- Command: `python3 -m scripts.smoke_video_75` from a clean detached checkout.
- Result: exit 0; JSON reported `verified=true`, `synthetic=true`, duration
  75 seconds, resolution `720x1280`, `ffprobe=passed`,
  `data_mutation=false`.
- This validates only the synthetic video gate. It does not qualify the full
  local CI controller or authorize a PC delivery.

The original workflow addition was commit `604826ad642435b374705fba1f6db803f316b4de`.
Its content is retained on the dedicated control branch; this PR changes its
trigger from automatic `pull_request` to explicit `workflow_dispatch`.
