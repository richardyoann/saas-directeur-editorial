#!/usr/bin/env bash
# Qualification locale Arvor sans merge, signature, livraison ni publication.
# Executer uniquement depuis un controleur relu et epingle hors PR candidate.
set -Eeuo pipefail
umask 077

usage() {
  printf 'Usage: bash scripts/qualify_arvor_ci_wsl.sh CONTROLLER_SHA PR214_SHA BASE_SHA\n' >&2
  exit 2
}
fail() {
  printf 'ARVOR_CI_QUALIFICATION_BLOCKED: %s\n' "$*" >&2
  exit 2
}
[[ $# -eq 3 ]] || usage
controller_sha=$1
candidate_sha=$2
base_sha=$3
sha_pattern='^[0-9a-f]{40}$'
[[ $controller_sha =~ $sha_pattern ]] || fail "controller SHA incomplet"
[[ $candidate_sha =~ $sha_pattern ]] || fail "candidate SHA incomplet"
[[ $base_sha =~ $sha_pattern ]] || fail "base SHA incomplet"

lab=${ARVOR_CI_LAB_DIR:-"$HOME/arvor-ci-lab"}
[[ $lab == /* && $lab != / && $lab != "$HOME" ]] || fail "lab path non borne"
[[ -d $lab && ! -L $lab ]] || fail "lab absent ou lien symbolique"
controller="$lab/ci-source"
candidate="$lab/pr214"
python="$lab/ci-venv/bin/python"
[[ -d $controller/.git && -d $candidate/.git ]] || fail "checkouts autonomes requis"
[[ -x $python ]] || fail "venv CI absent"
command -v docker >/dev/null || fail "Docker indisponible"
docker info >/dev/null || fail "moteur Docker inaccessible"

check_checkout() {
  local root=$1 expected=$2 actual status
  actual=$(git -C "$root" rev-parse HEAD) || fail "lecture HEAD impossible"
  [[ $actual == "$expected" ]] || fail "checkout non epingle : $root"
  status=$(git -C "$root" status --porcelain) || fail "git status impossible"
  [[ -z $status ]] || fail "checkout modifie : $root"
}
check_checkout "$controller" "$controller_sha"
check_checkout "$candidate" "$candidate_sha"
git -C "$candidate" merge-base --is-ancestor "$base_sha" "$candidate_sha" \
  || fail "base non ancetre du candidat"

cd "$controller"
printf 'Controleur: %s\nCandidat PR #214: %s\nBase: %s\n' \
  "$controller_sha" "$candidate_sha" "$base_sha"
"$python" -m unittest \
  tests.test_arvor_ci_wsl_qualification \
  tests.test_arvor_ci_host_supervisor \
  tests.test_arvor_ci_trusted_unittest \
  tests.test_arvor_ci_audit_snapshot \
  tests.test_arvor_local_ci \
  tests.test_arvor_ci_sandbox \
  tests.test_arvor_ci_evidence_verify -v \
  || fail "tests de controleur en echec"

# Seuls de nouveaux repertoires prives sont crees. Ne pas ecraser
# $lab/trusted, $lab/evidence ou un depot de travail preexistant.
trusted=$(mktemp -d "$lab/trusted-qualification.XXXXXXXX") \
  || fail "impossible de creer trusted"
evidence=$(mktemp -d "$lab/evidence-qualification.XXXXXXXX") \
  || fail "impossible de creer evidence"
chmod 755 "$trusted" # politique publique, lisible depuis conteneur UID 999
chmod 700 "$evidence" # journaux prives, jamais montes dans le conteneur
for filename in arvor_local_ci.py arvor_ci_gate.py \
    arvor_ci_trusted_unittest.py arvor_ci_supervised_entrypoint.sh \
    arvor_ci_trusted_gitleaks.toml arvor_ci_trusted_gitleaksignore; do
  [[ -f "scripts/$filename" && ! -L "scripts/$filename" ]] \
    || fail "politique de confiance manquante : $filename"
  install -m 644 "scripts/$filename" "$trusted/$filename"
done

# Reconstruction forcee de l'audit reseau au build ; execution ensuite
# hors reseau. Une preuve >24 h reste KO, jamais ignoree.
refresh=$(date -u +%Y%m%dT%H%M%SZ)
tag="arvor-ci:qualification-${controller_sha:0:12}"
docker build --progress=plain \
  --build-arg "SECURITY_AUDIT_REFRESH=$refresh" \
  -f ci/local/Dockerfile -t "$tag" . \
  || fail "build/audit image KO"
image_id=$(docker image inspect --format '{{.Id}}' "$tag") \
  || fail "identite image indisponible"
[[ $image_id =~ ^sha256:[0-9a-f]{64}$ ]] || fail "ID image non immuable"

printf 'Image: %s\nPolitique de confiance: %s\nPreuves privees: %s\n' "$image_id" "$trusted" "$evidence"
"$python" -m scripts.arvor_ci_host_supervisor \
  --image-id "$image_id" --checkout "$candidate" \
  --trusted "$trusted" --evidence "$evidence" \
  --sha "$candidate_sha" --base-sha "$base_sha" \
  --controller-sha "$controller_sha" --pr 214 --execute \
  || fail "16 gates hote KO (preuves conservees dans $evidence)"

shopt -s nullglob
receipts=()
for receipt_path in "$evidence"/*.json; do
  [[ $receipt_path == *.host.json ]] && continue
  receipts+=("$receipt_path")
done
[[ ${#receipts[@]} -eq 1 ]] || fail "attendu un seul recu hote"
host_observation="$evidence/$(basename "${receipts[0]}" .json).host.json"
policy_sha256=$("$python" -c 'from scripts.arvor_ci_trust import policy_digest; import sys; print(policy_digest(sys.argv[1]))' "$controller")
"$python" -m scripts.arvor_ci_evidence_verify \
  --receipt "${receipts[0]}" --host-observation "$host_observation" \
  --evidence-dir "$evidence" --checkout "$candidate" \
  --trusted-controller "$controller" --trusted-policy "$trusted" \
  --controller-sha "$controller_sha" \
  --image-id "$image_id" --policy-sha256 "$policy_sha256" \
  --sha "$candidate_sha" --base-sha "$base_sha" --pr 214 \
  || fail "integrite des preuves KO"

printf 'ARVOR_CI_LOCAL_GATES_AND_LOG_INTEGRITY_PASS\n'
printf 'Receipt: %s\n' "${receipts[0]}"
printf 'Provenance host independante verifiee; signature et publication distinctes. Merge/deploiement: NON.\n'
