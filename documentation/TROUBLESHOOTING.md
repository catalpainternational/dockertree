# Dockertree Troubleshooting Guide

## Port Already Allocated (e.g., `Bind for 0.0.0.0:5432 failed`)

### Symptom
- `docker compose up` fails with `driver failed programming external connectivity` or `Bind for 0.0.0.0:5432 failed: port is already allocated`
- Only one Dockertree worktree starts successfully; additional worktrees fail to start `db`, `redis`, or `web` containers
- Host ports 5432/6379/8000 randomly collide with other local stacks

### Root Cause
Older `docker-compose.worktree.yml` files published fixed host port mappings such as `5432:5432` and `8000:8000`. When multiple worktrees reuse those host ports, Docker cannot bind the second container, producing the `port is already allocated` error. This was masked previously because the compose override relied on `expose` only; once explicit `ports` blocks were added, conflicts surfaced.

### Solution
1. **Use env-driven port mappings**  
   Update `.dockertree/docker-compose.worktree.yml` so every service that publishes a host port uses the Dockertree placeholders:
   ```yaml
   services:
     db:
       expose:
         - "5432"
       ports:
         - "${DOCKERTREE_DB_HOST_PORT:-0}:5432"
     web:
       expose:
         - "8000"
       ports:
         - "${DOCKERTREE_WEB_HOST_PORT:-0}:8000"
     redis:
       ports:
         - "${DOCKERTREE_REDIS_HOST_PORT:-0}:6379"
   ```
   The `:-0` default lets Docker pick a random free port when running against legacy environments that are missing the new variables.

2. **Let Dockertree assign unique host ports per worktree**  
   The environment manager now writes three new entries to each worktree's `.dockertree/env.dockertree`:
   ```
   DOCKERTREE_DB_HOST_PORT=58xxx
   DOCKERTREE_REDIS_HOST_PORT=57xxx
   DOCKERTREE_WEB_HOST_PORT=58xxx
   ```
   These values are selected from high-numbered ranges to avoid system services and are guaranteed to be unique across all existing worktrees. When you create a new worktree (`dockertree create <branch>`), the CLI auto-assigns and logs the chosen ports.

3. **Retrofit existing worktrees**  
   Delete and recreate the worktree (`dockertree delete <branch>` followed by `dockertree create <branch>`) so the new env file is generated with unique ports. If recreation is not possible, manually edit `<worktree>/.dockertree/env.dockertree` and add unique values for `DOCKERTREE_DB_HOST_PORT`, `DOCKERTREE_REDIS_HOST_PORT`, and `DOCKERTREE_WEB_HOST_PORT`.

### Verification
- `docker compose -p <project>-<branch> ps` shows each service running with distinct published ports.
- `docker compose port db 5432` (or `web 8000`, `redis 6379`) matches the values recorded in `.dockertree/env.dockertree`.
- Bringing up multiple worktrees simultaneously no longer produces `port is already allocated`.

## Workers Not Processing Jobs / Database Connection Failures

### Symptom
- RQ workers fail to start or get stuck in restart loops
- Error messages like: `could not translate host name "db" to address`
- Workers cannot connect to database/Redis on central droplet
- Jobs remain queued in Redis but are never processed

### Root Cause
When using Dockertree with a central droplet architecture (worker servers connecting to hub server's database/Redis), the worker's `.env` file may contain hardcoded service names (`DB_HOST=db`, `REDIS_HOST=redis`) that override the Docker environment variables set from `.dockertree/env.dockertree`.

Additionally, if your project's `manage.py` uses `load_dotenv(override=True)`, it will override Docker environment variables with values from the `.env` file.

### Solution

#### 1. Ensure Docker Compose Uses Variable Substitution
In `.dockertree/docker-compose.worktree.yml`, use variable substitution instead of hardcoded values:

```yaml
environment:
  DB_HOST: ${DB_HOST:-db}           # Not: DB_HOST: db
  REDIS_HOST: ${REDIS_HOST:-redis}  # Not: REDIS_HOST: redis
  DATABASE_URL: postgres://${POSTGRES_USER:-biuser}:${POSTGRES_PASSWORD:-bipassword}@${DB_HOST:-db}:5432/business_intelligence
```

This allows `.dockertree/env.dockertree` to override the defaults.

#### 2. Update manage.py to Honor Docker Environment Variables
If your `manage.py` has `override=True`, remove it to preserve Docker environment variables:

**Before:**
```python
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)
```

**After:**
```python
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # override=False by default
```

This ensures that Docker environment variables (set from `.dockertree/env.dockertree`) take precedence over `.env` file values.

#### 3. Verify .dockertree/env.dockertree Contains Correct Values
When `dockertree droplet create` is run with `--central-droplet-name`, it should write:

```bash
DB_HOST=10.116.0.13      # VPC IP of central droplet
REDIS_HOST=10.116.0.13   # VPC IP of central droplet
```

Check that these values are present in `.dockertree/env.dockertree` on the worker server.

### Verification

After making these changes, restart the worker service:

```bash
docker restart <container-name>
```

Check logs to confirm:
- Database connection succeeds
- Workers start successfully
- Jobs begin processing from the queue

### Environment Variable Precedence

Docker Compose loads environment variables in this order (later overrides earlier):
1. `.env` file
2. `.dockertree/env.dockertree` (overrides `.env`)
3. `environment` section in docker-compose.yml (uses variable substitution from above)

Python's `load_dotenv(override=False)` respects existing environment variables, so Docker-set values are preserved.

