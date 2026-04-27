#!/bin/bash
LOG=/srv/repos/windy-pro/THE_CLINIC/huggingface-uploads/upload_parallel.log
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [scheduler] Daily batch starting" >> $LOG

# Verify repo creation quota is available.
# Use a UUID-suffixed probe-repo name so HF can't single-name-rate-limit us.
PROBE_NAME="WindyWord/_probe-$(date +%s)-$RANDOM"
python3 -c "
from huggingface_hub import create_repo, HfApi
import sys
try:
    create_repo(repo_id='$PROBE_NAME', repo_type='model', exist_ok=False)
    HfApi().delete_repo(repo_id='$PROBE_NAME', repo_type='model')
    sys.exit(0)
except Exception as e:
    # Distinguish 429 (true rate-limit) from 403/409/etc (other auth/conflict issues
    # that we'd want to surface, not silently sleep-loop on).
    msg = str(e)
    if '429' in msg:
        sys.exit(1)
    print('PROBE_UNEXPECTED:', msg[:200], file=sys.stderr)
    sys.exit(2)
" 2>&1
RC=$?

if [ $RC -eq 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [scheduler] Quota available, launching upload" >> $LOG
    nohup python3 /srv/repos/windy-pro/THE_CLINIC/scripts/upload_parallel.py --workers 4 >> /tmp/hf_parallel.log 2>&1 &
elif [ $RC -eq 1 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [scheduler] Quota still exhausted (429), waiting another hour" >> $LOG
    sleep 3600
    exec $0
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [scheduler] Probe failed with non-429 error (rc=$RC); waiting an hour" >> $LOG
    sleep 3600
    exec $0
fi
