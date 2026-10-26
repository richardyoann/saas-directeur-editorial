"""Opt-in real application-adapter probe. Leaves one synthetic object for admin cleanup.

No production configuration is changed; credentials and upstream errors never printed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.media import s3 as storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-probe', action='store_true', required=True)
    parser.parse_args()
    from botocore.exceptions import ClientError
    ids = uuid4(), uuid4(), uuid4()
    report = {'scope': 'real_application_adapter', 'outcome': 'failed'}
    try:
        report['sha'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
            text=True, stderr=subprocess.DEVNULL).strip()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'probe.wav'
            payload = b'arvor-synthetic-s3-integration-probe\n'
            source.write_bytes(payload)
            reference = storage.put_file(source, *ids, 'voice')
            report['cleanup_reference'] = {'bucket': reference['bucket'], 'key': reference['key']}
            output = storage.get_file(reference, Path(directory) / 'download.wav', *ids, 'voice')
            if hashlib.sha256(output.read_bytes()).hexdigest() != reference['sha256']:
                raise storage.MediaStorageError('probe_integrity_failed')
            # Only the synthetic object just created is ever targeted.
            try:
                storage.client().delete_object(Bucket=reference['bucket'], Key=reference['key'])
            except ClientError as error:
                if error.response.get('Error', {}).get('Code') not in {'AccessDenied', 'AllAccessDisabled'}:
                    raise storage.MediaStorageError('probe_delete_check_failed') from None
            else:
                raise storage.MediaStorageError('probe_delete_unexpectedly_allowed')
        report.update(outcome='passed', checks=['https_ca', 'put', 'get', 'sha256', 'delete_denied'])
    except Exception:
        # Never stringify SDK/OS exceptions, paths or credentials.
        report['error'] = 'media_s3_probe_failed'
    print(json.dumps(report, sort_keys=True))
    return 0 if report['outcome'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
