"""Validate a maintainer-created, exact-SHA delivery approval; never deploy here."""
import json
import os
import re
from urllib.request import Request, urlopen

REPOSITORY = "richardyoann/saas-directeur-editorial"


def validate(ref, repository, main_sha, branch_sha):
    match = re.fullmatch(r"delivery-approved/([0-9a-f]{40})", ref)
    if repository != REPOSITORY or not match:
        raise ValueError("Invalid delivery approval reference")
    sha = match.group(1)
    if sha != main_sha or sha != branch_sha:
        raise ValueError("Approval no longer matches current main")
    return sha


def main():
    repository = os.environ["APPROVAL_REPOSITORY"]
    ref = os.environ["APPROVAL_REF"]
    # Validate before using event values in an API URL.
    if repository != REPOSITORY or not re.fullmatch(r"delivery-approved/[0-9a-f]{40}", ref):
        raise ValueError("Invalid delivery approval reference")
    def get(path):
        request = Request(
            "https://api.github.com/repos/" + REPOSITORY + path,
            headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                     "Accept": "application/vnd.github+json"},
        )
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    approved = validate(ref, repository,
                        get("/git/ref/heads/main")["object"]["sha"],
                        get("/git/ref/heads/" + ref)["object"]["sha"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("sha=" + approved + "\n")


if __name__ == "__main__":
    main()
