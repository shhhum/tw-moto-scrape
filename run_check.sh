#!/usr/bin/env bash
# Banqiao 普通重型機車 slot check + ntfy push, for local scheduling (launchd/cron).
# Pushes to ntfy.sh/tw_moto_exams on EVERY run: slots open / no slots / error.
set -u
cd "$(dirname "$0")"

source .venv/bin/activate
export MVDIS_STATIONS=板橋 MVDIS_LICENSES=普通重型機車

out=$(python3 check_moto_test.py 2>&1)
code=$?

# ntfy titles stay ASCII — ntfy headers don't take raw UTF-8. Chinese goes in the body.
if [ $code -ne 0 ]; then
    title="Banqiao checker ERROR"
    priority="high"
    body="$out"
elif printf '%s' "$out" | grep -q "^Upcoming motorcycle road-test slots"; then
    title="Banqiao slots OPEN"
    priority="high"
    body="$out
Book: https://www.mvdis.gov.tw/m3-emv-trn/exm/locations#"
else
    title="Banqiao check"
    priority="default"
    body="No 普通重型機車 slots at 板橋 this hour."
fi

echo "$out"
curl -sS --fail-with-body \
    -H "Title: $title" \
    -H "Priority: $priority" \
    -H "Tags: motor_scooter" \
    -d "$body" \
    https://ntfy.sh/tw_moto_exams
