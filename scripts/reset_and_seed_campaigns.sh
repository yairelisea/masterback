#!/usr/bin/env bash
set -euo pipefail

# Purge all existing campaigns and seed a fresh set, then kick off run-all for each.
# Requirements: curl, jq
# Usage:
#   export API="https://masterback.onrender.com"
#   export TOKEN="<ADMIN_JWT>"    # or set ADMIN_EMAIL to login
#   ./scripts/reset_and_seed_campaigns.sh

API="${API:-https://masterback.onrender.com}"
SIZE="${SIZE:-35}"
DAYS_BACK="${DAYS_BACK:-30}"
LANG="${LANG:-es-419}"
COUNTRY="${COUNTRY:-MX}"

if [[ -z "${TOKEN:-}" ]]; then
  if [[ -n "${ADMIN_EMAIL:-}" ]]; then
    echo "Logging in to get admin token..."
    TOKEN="$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d "{\"email\":\"$ADMIN_EMAIL\",\"name\":\"${ADMIN_NAME:-Admin}\"}" | jq -r .access_token)"
  else
    echo "ERROR: set TOKEN or ADMIN_EMAIL env var" >&2
    exit 1
  fi
fi
AUTH=(-H "Authorization: Bearer $TOKEN")

echo "Fetching current campaigns..."
CURR="$(curl -sS "$API/admin/campaigns" "${AUTH[@]}")"
IDS=( $(echo "$CURR" | jq -r '.[].id') )
if (( ${#IDS[@]} > 0 )); then
  echo "Purging ${#IDS[@]} campaigns..."
  BODY=$(printf '{"ids":%s}' "$(printf '%s\n' "${IDS[@]}" | jq -R . | jq -s .)")
  curl -sS -X POST "$API/admin/campaigns/purge" "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BODY" | jq .
else
  echo "No campaigns to purge."
fi

echo "Seeding campaigns..."
SEED=$(jq -n \
  --arg size "$SIZE" \
  --arg days "$DAYS_BACK" \
  '[
    {name:"Marcelo Abundiz Diputado", query:"Marcelo Abundiz", city_keywords:["Diputado Local","Morena","Tamaulipas","Altamira"]},
    {name:"Olga Sosa Ruiz Senadora", query:"Olga Sosa Ruiz", city_keywords:["Senadora","Tamaulipas","Morena"]},
    {name:"Erasmo Gonzales Alcalde Madero", query:"Erasmo Gonzales Robledo", city_keywords:["Ciudad Madero","Tamaulipas","Morena","Alcalde"]},
    {name:"Luis Susarrey SPGG", query:"Luis Susarrey", city_keywords:["San Pedro Garza García","PAN Secretario del Ayuntamiento"]}
  ]')

NEW_IDS=()
for row in $(echo "$SEED" | jq -c '.[]'); do
  name=$(echo "$row" | jq -r .name)
  query=$(echo "$row" | jq -r .query)
  ckeys=$(echo "$row" | jq -c .city_keywords)
  BODY=$(jq -n --arg name "$name" --arg q "$query" --argjson ckeys "$ckeys" \
    --argjson size "$SIZE" --argjson days "$DAYS_BACK" \
    '{name:$name, query:$q, size:$size, days_back:$days, lang:"es-419", country:"MX", city_keywords:$ckeys, plan:"BASIC", autoEnabled:true}')
  echo "Creating: $name"
  CAMP=$(curl -sS -X POST "$API/admin/campaigns" "${AUTH[@]}" -H 'Content-Type: application/json' -d "$BODY")
  echo "$CAMP" | jq .
  cid=$(echo "$CAMP" | jq -r .id)
  if [[ "$cid" != "null" && -n "$cid" ]]; then
    NEW_IDS+=("$cid")
  fi
done

echo "Kicking off run-all for seeded campaigns..."
for cid in "${NEW_IDS[@]}"; do
  echo "Run-all: $cid"
  curl -sS -X POST "$API/admin/campaigns/$cid/run-all" "${AUTH[@]}" | jq .
done

echo "Done. You can monitor with:"
for cid in "${NEW_IDS[@]}"; do
  echo "  curl -s \"$API/admin/campaigns/$cid/overview\" ${AUTH[*]} | jq"
done

