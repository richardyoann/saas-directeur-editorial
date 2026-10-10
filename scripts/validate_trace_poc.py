"""Save attributable validation results; never converts skipped tests into passes."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__ == '__main__':
    directory = ROOT / 'validation'
    directory.mkdir(exist_ok=True)
    suites = [('trace', 'test_traceability*.py'),('generation','test_generate.py'),('full_windows','test_*.py')]
    summary = {}
    for name, pattern in suites:
        with (directory / (name+'.txt')).open('w',encoding='utf-8') as output:
            result = unittest.TextTestRunner(stream=output,verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
        summary[name] = {'run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped)}
    (directory/'results.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary))
    sys.exit(0 if all(summary[n]['errors']==summary[n]['failures']==0 for n in ('trace','generation')) else 1)
