"""Trusted gate selector for a host-owned docker exec (no evidence writer).
No PR-controlled test framework can select an arbitrary command or rewrite
the host's captured exit status. Run ONLY from the /trusted readonly mount.
"""
import argparse
import os
from pathlib import Path
import sys
if __package__:
    from .arvor_local_ci import GATES, commands, validate_db
else:
    from arvor_local_ci import GATES, commands, validate_db


def supervised_commands(p312, p314, base):
    """Preserve legacy gates, replace only host-supervised unittest launchers."""
    result = commands(p312, p314, base)
    trusted = "/trusted/arvor_ci_trusted_unittest.py"
    for name, interpreter, suite in (
        ("regression_312", p312, "regression"),
        ("regression_314", p314, "regression"),
        ("browser", p312, "browser"),
    ):
        result[name] = [str(interpreter), "-I", trusted, "--suite", suite]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", required=True, choices=GATES)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    if os.environ.get("ARVOR_CI_ISOLATED") != "1":
        parser.error("Missing isolated sandbox marker")
    validate_db(os.environ)
    argv = supervised_commands(
        Path("/opt/arvor/py312/bin/python"),
        Path("/opt/arvor/py314/bin/python"),
        args.base_sha,
    )[args.gate]
    os.environ["STUDIO_BROWSER_TESTS"] = "yes"
    os.execvpe(argv[0], argv, os.environ)


if __name__ == "__main__":
    main()
