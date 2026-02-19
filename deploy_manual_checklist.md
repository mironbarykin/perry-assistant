# Deploy Manual Checklist

1. Confirm remote `.env` exists at `~/projects/perry/.env`.
2. Run `build.bat`.
3. Verify script prints all six stages and final success message.
4. On remote host, verify `docker ps` shows container `perry` running.
5. Force a failed deployment once (invalid env or bad image) and confirm rollback restarts previous image.
6. Verify old tar artifacts are pruned on remote host after repeated deploys.

