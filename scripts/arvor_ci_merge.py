"""Fail-closed procedural merge gate; not a replacement for GitHub branch protection.

Run from an independently reviewed checkout, never from candidate code. The
qualification manifest is signed by a separate host/OpenSSL bootstrap authority.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess

REPO = 'richardyoann/saas-directeur-editorial'


def validate(manifest, pr, head, base, review_bytes, now=None):
    now = now or datetime.now(timezone.utc)
    if (manifest.get('schema') != 'arvor-merge-qualification-v1'
            or manifest.get('repo') != REPO or manifest.get('pr') != pr
            or manifest.get('head') != head or manifest.get('base') != base
            or manifest.get('status') != 'success'
            or manifest.get('review_sha256') != hashlib.sha256(review_bytes).hexdigest()):
        raise ValueError('Qualification identity, signature input or review mismatch')
    finished = datetime.fromisoformat(manifest['finished_at'])
    if not finished.tzinfo or not timedelta(0) <= now - finished <= timedelta(hours=2):
        raise ValueError('Qualification expired or future dated')
    checks = manifest.get('checks')
    if not isinstance(checks, dict) or not checks or any(value != 'passed' for value in checks.values()):
        raise ValueError('Incomplete qualification')
    required = {'python312', 'python314', 'regression', 'postgres', 'browser',
                'dependencies', 'secrets', 'supply_chain', 'syntax', 'review', 'provenance'}
    if not required.issubset(checks):
        raise ValueError('Mandatory checks absent')
    if pr == 214 and not {'video75', 'sixteen_gates', 'attestation'}.issubset(checks):
        raise ValueError('Application attestation gates missing')
    if pr == 215 and 'independent_bootstrap' not in checks:
        raise ValueError('Independent controller bootstrap missing')
    review = json.loads(review_bytes)
    if (review.get('head') != head or review.get('base') != base
            or review.get('blocking_findings') != 0 or review.get('kind') != 'independent-automated-review'):
        raise ValueError('Final independent review absent or blocking')
    return True


def github(*args):
    return json.loads(subprocess.check_output(['gh', 'api', *args], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'signature', 'public-key', 'review'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--public-key-sha256', required=True)
    parser.add_argument('--pr', type=int, choices=(214, 215), required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if hashlib.sha256(args.public_key.read_bytes()).hexdigest() != args.public_key_sha256:
        raise ValueError('Bootstrap key pin mismatch')
    subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(args.public_key),
                    '-rawin', '-in', str(args.manifest), '-sigfile', str(args.signature)], check=True)
    validate(json.loads(args.manifest.read_bytes()), args.pr, args.head, args.base, args.review.read_bytes())
    remote = github(f'repos/{REPO}/pulls/{args.pr}')
    branch = github(f'repos/{REPO}/branches/main')
    if (remote['state'] != 'open' or remote['draft'] or not remote.get('mergeable')
            or remote['head']['sha'] != args.head or remote['base']['sha'] != args.base
            or branch['commit']['sha'] != args.base):
        raise ValueError('Remote changed, draft or merge conflict')
    # No admin override: GitHub itself enforces any native required checks/reviews.
    if args.execute:
        result = github('--method', 'PUT', f'repos/{REPO}/pulls/{args.pr}/merge',
                        '-f', 'merge_method=merge', '-f', 'sha=' + args.head,
                        '-f', f'commit_title=Merge PR #{args.pr}: qualified local CI [skip ci]')
        if result.get('merged') is not True:
            raise ValueError('GitHub did not merge')
        observed = github(f'repos/{REPO}/pulls/{args.pr}')
        if observed.get('merged') is not True:
            raise ValueError('Merge not observed')
        print(json.dumps({'pr': args.pr, 'merged': True, 'merge_sha': observed['merge_commit_sha']}))
    else:
        print('Qualification verified; no merge performed')


if __name__ == '__main__':
    main()
