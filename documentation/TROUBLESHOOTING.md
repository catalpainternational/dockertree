# Dockertree Troubleshooting Guide

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

