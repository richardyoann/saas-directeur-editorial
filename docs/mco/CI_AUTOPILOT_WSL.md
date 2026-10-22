# Arvor — Automatic local CI, candidate only

**Not installed or activated on Windows/WSL.** No merging, PC delivery, secrets or service changes are performed by this PR. The existing GitHub Actions remain unchanged until a separately reviewed activation.

The trusted controller runs via a systemd **user timer every ten minutes**, while WSL is running. It polls private same-repository PRs on main, including drafts; checks full head and base SHAs against fetched Git refs; creates temporary worktrees; runs all nine isolated gates through trusted ops/ci/run_and_report.sh; seals reports using a private HMAC key; publishes only external GitHub statuses and sanitized Slack summaries. One PR per tick limits load. New head/base SHA triggers re-check; unchanged result is retried the next day; infrastructure failure after two hours. flock prevents overlapping runs. No OpenCode AI opinion constitutes a gate; OpenCode may continue developing branches independently.

The controller must be a separately *reviewed, clean, fixed SHA* supplied as ARVOR_CI_CONTROLLER_SHA, never unchecked PR code. Pulls from forks and heads that are not descendants of main are refused. No credentials or Docker socket enter test containers; no business volumes/data are mounted.

After an independent, explicit approval to install on the PC, copy ops/ci/systemd/arvor-ci-poll.service and .timer to ~/.config/systemd/user and configure ~/.config/arvor-ci/autopilot.env, mode 0600, with nonsecret settings:

    ARVOR_CI_CONTROLLER_ROOT=/home/yoann_admin/saas-directeur-editorial-github
    ARVOR_CI_CONTROLLER_SHA=<exact_approved_sha40>
    ARVOR_CI_SLACK_CHANNEL=<private_channel_id>
    ARVOR_CI_IMAGE_ID_312=<approved_sha256_image_id>
    ARVOR_CI_IMAGE_ID_314=<approved_sha256_image_id>
    ARVOR_CI_POSTGRES_IMAGE_ID=<approved_sha256_image_id>

Use systemd LoadCredential for github.token, slack.token and attestation.key in ~/.config/arvor-ci/, mode 0600. GitHub token must only have read PR/contents and write commit-status/issue-comment privileges, *not* administration/merge/deploy. Configure a separate read-only Git credential or SSH key for fetch. Inspect and approve Docker image origin/digests. Review ReadWritePaths for the isolated controller path and Docker permissions before service activation.

Following approval and completed WSL integration tests only:

    mkdir -p ~/.config/systemd/user
    cp ops/ci/systemd/arvor-ci-poll.{service,timer} ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now arvor-ci-poll.timer
    systemctl --user list-timers --all
    journalctl --user -u arvor-ci-poll.service -n 30 --no-pager

Important: the watcher *cannot run if Windows is off or WSL is shut down*. Continuous operation after Windows reboot requires separately approved WSL startup or a dedicated CI machine. This PR does not install either.

Acceptance criteria: controller reviewed, all nine gates run on one real sample PR in isolated WSL, 0 skipped, attestations verified, GitHub status tied to same SHA, Slack acknowledgment received and tested on both success and failure. Disable redundant GitHub Actions only in a separate approval/PR after parity proven. Keep #214 draft, no auto merge and no deployment PC without explicit full SHA approval.
