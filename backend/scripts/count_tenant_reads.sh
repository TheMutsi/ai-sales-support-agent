#!/bin/sh
# How many times does the API read the `tenants` table while serving 100 authenticated requests?
# This is the measurement behind ADR-0016 ("99 reads for 100 requests without the cache, 3 with
# it"). It needs the local stack: `docker compose up -d db`, a migrated and seeded database
# (`python -m app.db.seed`), and Postgres reachable as in .env. Run it from `backend/`, once on a
# branch with the cache and once on one without, and compare. It starts and stops its own server.
K=pk_dev_mewflow_local; O="Origin: http://127.0.0.1:8080"; J="Content-Type: application/json"
q() {
  docker compose exec -T db psql -U mewflow -d mewflow -t -A -c \
    "select coalesce(seq_scan,0)+coalesce(idx_scan,0) from pg_stat_user_tables where relname='tenants';"
}
pkill -f "uvicorn app.main"; sleep 1
(.venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/mew-api.log 2>&1 &); sleep 5
R=$(curl -s -X POST localhost:8000/api/conversations -H "$J" -H "$O" -d "{\"api_key\":\"$K\"}")
TOK=$(echo "$R" | python3 -c "import json,sys;print(json.load(sys.stdin)['session_token'])")
CID=$(echo "$R" | python3 -c "import json,sys;print(json.load(sys.stdin)['conversation_id'])")
sleep 3; BEFORE=$(q)  # Postgres reports table statistics with a short delay
for i in $(seq 1 100); do
  curl -s -o /dev/null -H "Authorization: Bearer $TOK" -H "$O" "localhost:8000/api/conversations/$CID/messages"
done
sleep 3; AFTER=$(q)
echo "reads of tenants during 100 requests: $((AFTER - BEFORE))"
pkill -f "uvicorn app.main"
