# Dockertree: Git Worktrees for Isolated Development Environments

This document defines the complete design and implementation plan for using Git worktrees to create isolated development environments with Docker Compose and Caddy reverse proxy.

## Overview

Dockertree enables developers to create isolated development environments for each feature branch using Git worktrees, Docker Compose, and a global Caddy reverse proxy for dynamic routing.

### Key Features
- **Isolated Environments**: Each worktree has its own database, Redis, and media storage
- **No Port Conflicts**: Services use internal networking with dynamic routing
- **Volume Isolation**: Branch-specific volumes with data copying
- **Global Caddy**: Single reverse proxy routes traffic to correct worktree
- **Simple CLI**: Easy commands for worktree lifecycle management

## Architecture

### Core Components
1. **Git Worktrees**: Isolated working directories for each branch
2. **Docker Compose Override**: `docker-compose.dockertree.yml` for isolated services
3. **Volume Isolation**: Branch-specific volumes with data copying
4. **Global Caddy**: Dynamic routing based on container labels
5. **External Network**: `dockertree_caddy_proxy` network for service communication

### Service Structure
```
Default Services (unchanged):
- db (ports: 5432:5432)
- redis (no ports)
- web (ports: 8000:8000)
- rq-worker-1
- caddy (ports: 80:80, 443:443)

Dockertree Override Services (docker-compose.dockertree.yml):
- db (expose: 5432, dockertree_caddy_proxy network)
- redis (expose: 6379, dockertree_caddy_proxy network)
- web (expose: 8000, caddy labels, dockertree_caddy_proxy network)
- rq-worker-1 (dockertree_caddy_proxy network)
- caddy (expose: 80, 443, dockertree_caddy_proxy network)
```

## CLI Commands

### Global Caddy Management
```bash
dockertree start    # Start global Caddy container
dockertree stop     # Stop global Caddy container
```

### Worktree Management
```bash
dockertree create <branch-name>       # Create worktree in worktrees directory
dockertree up <branch-name> -d        # Start worktree environment for branch
dockertree down <branch-name>         # Stop worktree environment for branch
dockertree delete <branch-name>       # Delete worktree completely
dockertree list                       # List active worktrees
```

### Volume Management
```bash
dockertree volumes list                    # List all worktree volumes
dockertree volumes size                    # Show volume sizes
dockertree volumes backup <branch-name>     # Backup worktree volumes
dockertree volumes restore <branch-name> <backup-file.tar>  # Restore worktree volumes
dockertree volumes clean <branch-name>     # Clean up worktree volumes
```

## Usage Workflow

### Complete Development Workflow
```bash
# 1. Start global Caddy
dockertree start

# 2. Create worktree
dockertree create feature-auth

# 3. Start worktree environment
dockertree up feature-auth -d

# 4. Access environment
open http://feature-auth.localhost

# 5. Stop worktree
dockertree down feature-auth

# 6. Remove worktree
dockertree remove feature-auth

# 7. Stop global Caddy
dockertree stop
```

### Multiple Worktrees
```bash
# Create multiple worktrees
dockertree create feature-payments
dockertree create feature-notifications

# Each worktree runs independently
# Access: http://feature-payments.localhost
# Access: http://feature-notifications.localhost
```

## Implementation Phases

### Phase 1: Infrastructure Setup
**Goal**: Prepare Docker infrastructure for dockertree functionality

#### 1.1 Docker Network Setup
- Create external `dockertree_caddy_proxy` network
- Ensure network isolation between worktrees

#### 1.2 Docker Compose Override File
- Create `docker-compose.dockertree.yml` override file with `dockertree` profile
- Configure services with `expose:` instead of `ports:`
- Add Caddy labels for dynamic routing
- Connect services to `dockertree_caddy_proxy` network
- **Conservative**: No changes to existing `docker-compose.yml`

#### 1.3 Volume Strategy Implementation
- Implement branch-specific volume naming: `${COMPOSE_PROJECT_NAME}_*`
- Create volume copy functionality
- Ensure data isolation between worktrees

#### 1.4 Caddy Dynamic Configuration
- Create dynamic Caddyfile for service discovery
- Implement container label-based routing
- Configure health checks and error handling

### Phase 2: CLI Tool Development
**Goal**: Build the `dockertree` command-line interface

#### 2.1 Core CLI Commands
- `dockertree create <branch-name>`: Worktree creation with volume setup
- `dockertree up <branch-name> -d`: Uses `docker compose -f docker-compose.yml -f docker-compose.dockertree.yml up -d`
- `dockertree down <branch-name>`: Stop worktree environment
- `dockertree delete <branch-name>`: Complete worktree deletion

#### 2.2 Global Caddy Management
- `dockertree start`: Start global Caddy container
- `dockertree stop`: Stop global Caddy container
- Network creation and management

#### 2.3 Worktree Lifecycle Management
- Git worktree creation and removal
- Environment file configuration
- Volume creation and data copying
- Directory navigation

#### 2.4 Error Handling and Validation
- Worktree directory validation
- Volume existence checks
- Container conflict detection
- User-friendly error messages

### Phase 3: Volume Isolation
**Goal**: Implement complete data isolation between worktrees

#### 3.1 Volume Naming Convention

**Current Volume Analysis:**
From the existing `docker-compose.yml`:
```yaml
volumes:
  postgres_data:      # PostgreSQL data
  redis_data:         # Redis cache data  
  media_files:        # User uploads/media
  caddy_data:         # Caddy SSL certificates
  caddy_config:       # Caddy configuration
```

**Worktree-Specific Volume Naming:**
For worktree "feature-branch":
```yaml
volumes:
  feature-branch_postgres_data:
  feature-branch_redis_data:
  feature-branch_media_files:
  # Shared volumes (not worktree-specific)
  caddy_data:
  caddy_config:
```

#### 3.2 Volume Copy Strategy

**When Creating a New Worktree:**

1. **Create new named volumes:**
```bash
# Create worktree-specific volumes
docker volume create feature-branch_postgres_data
docker volume create feature-branch_redis_data  
docker volume create feature-branch_media_files
```

2. **Copy data from existing volumes (if they exist):**
```bash
# Copy PostgreSQL data
docker run --rm \
  -v postgres_data:/source \
  -v feature-branch_postgres_data:/dest \
  alpine sh -c "cp -r /source/* /dest/"

# Copy Redis data  
docker run --rm \
  -v redis_data:/source \
  -v feature-branch_redis_data:/dest \
  alpine sh -c "cp -r /source/* /dest/"

# Copy media files
docker run --rm \
  -v media_files:/source \
  -v feature-branch_media_files:/dest \
  alpine sh -c "cp -r /source/* /dest/"
```

#### 3.3 Volume Copy Implementation

**dockertree CLI Volume Copy Function:**
```bash
#!/bin/bash

copy_volume() {
    local source_volume=$1
    local target_volume=$2
    
    echo "Copying volume $source_volume to $target_volume..."
    
    # Check if source volume exists
    if ! docker volume inspect $source_volume >/dev/null 2>&1; then
        echo "Source volume $source_volume does not exist, creating empty target volume"
        docker volume create $target_volume
        return 0
    fi
    
    # Copy volume data
    docker run --rm \
        -v $source_volume:/source:ro \
        -v $target_volume:/dest \
        alpine sh -c "cp -r /source/* /dest/ 2>/dev/null || true"
    
    echo "Volume copy completed: $source_volume -> $target_volume"
}

# Usage for worktree "feature-branch"
copy_volume "postgres_data" "feature-branch_postgres_data"
copy_volume "redis_data" "feature-branch_redis_data"  
copy_volume "media_files" "feature-branch_media_files"
```

#### 3.4 Docker Compose Override for Worktrees

Each worktree uses the main `docker-compose.yml` with the `docker-compose.dockertree.yml` override:

```yaml
# docker-compose.dockertree.yml
services:
  db:
    profiles:
      - dockertree
    expose:
      - "5432"
    ports: []
    networks:
      - internal
      - dockertree_caddy_proxy

  redis:
    profiles:
      - dockertree
    expose:
      - "6379"
    networks:
      - internal
      - dockertree_caddy_proxy

  web:
    profiles:
      - dockertree
    expose:
      - "8000"
    ports: []
    labels:
      - "caddy.proxy=${COMPOSE_PROJECT_NAME:-test_project}.localhost"
      - "caddy.proxy.reverse_proxy=web:8000"
      - "caddy.proxy.health_check=/health/"
    networks:
      - internal
      - web
      - dockertree_caddy_proxy

  rq-worker-1:
    profiles:
      - dockertree
    networks:
      - internal
      - web
      - dockertree_caddy_proxy

  caddy:
    profiles:
      - dockertree
    expose:
      - "80"
      - "443"
    ports: []
    networks:
      - web
      - dockertree_caddy_proxy

networks:
  dockertree_caddy_proxy:
    external: true
```

#### 3.5 Worktree Creation Process

**Complete Worktree Creation Workflow:**
```bash
dockertree create feature-branch
```

**What happens:**
1. Create Git worktree: `git worktree add ../feature-branch feature-branch`
2. Copy `.env` file to worktree
3. Create worktree-specific volumes:
   ```bash
   docker volume create feature-branch_postgres_data
   docker volume create feature-branch_redis_data
   docker volume create feature-branch_media_files
   ```
4. Copy data from existing volumes (if they exist)
5. Generate `.dockertree/env.dockertree` with worktree-specific settings
6. Start the worktree environment: `docker compose -f docker-compose.yml -f docker-compose.dockertree.yml up -d`

#### 3.6 Volume Categories

**Worktree-Specific Volumes:**
- `{worktree-name}_postgres_data` - Database data (isolated per worktree)
- `{worktree-name}_redis_data` - Cache data (isolated per worktree)
- `{worktree-name}_media_files` - User uploads (isolated per worktree)

**Shared Volumes:**
- `caddy_data` - SSL certificates and Caddy configuration (shared across all worktrees)
- `caddy_config` - Caddy configuration files (shared)

#### 3.7 Volume Cleanup Strategy

**When Removing a Worktree:**
```bash
dockertree remove feature-branch
```

**What happens:**
1. Stop and remove all worktree containers
2. Remove worktree-specific volumes:
   ```bash
   docker volume rm feature-branch_postgres_data
   docker volume rm feature-branch_redis_data
   docker volume rm feature-branch_media_files
   ```
3. Remove worktree directory
4. Keep shared volumes (caddy_data, caddy_config) intact

#### 3.8 Error Handling

**Volume Copy Failures:**
- If source volume doesn't exist, create empty target volume
- If copy fails, log error but continue with empty volume
- Provide clear error messages for troubleshooting

**Volume Cleanup Failures:**
- Check if volumes are in use before removal
- Provide force option for cleanup: `dockertree remove --force feature-branch`
- Log warnings for volumes that couldn't be removed

#### 3.9 Security Considerations

**Volume Isolation:**
- Each worktree's volumes are completely isolated
- No cross-worktree data access possible
- Shared volumes (caddy) are read-only for worktrees

**Data Protection:**
- Worktree removal requires explicit confirmation
- Backup before removal option
- Volume size monitoring to prevent disk space issues

### Phase 4: Dynamic Routing
**Goal**: Implement Caddy-based dynamic routing for worktrees

#### 4.1 Container Label Configuration
```yaml
labels:
  - "caddy.proxy=${COMPOSE_PROJECT_NAME}.localhost"
  - "caddy.proxy.reverse_proxy=web-dockertree:8000"
  - "caddy.proxy.health_check=/health/"
```

#### 4.2 Dynamic Caddyfile
- Service discovery based on container labels
- Health check configuration
- Error handling and fallbacks
- Static file serving for media files

#### 4.3 Network Configuration
- External `dockertree_caddy_proxy` network setup
- Service communication between worktrees
- Port isolation and security

### Phase 5: Environment Configuration
**Goal**: Configure worktree-specific environment variables

#### 5.1 Environment File Management
- Copy `.env` file to worktree
- Add worktree-specific variables:
  - `COMPOSE_PROJECT_NAME=branch-name`
  - `SITE_DOMAIN=branch-name.localhost`
  - `ALLOWED_HOSTS=localhost,127.0.0.1,branch-name.localhost,*.localhost`

#### 5.2 Database Isolation
- Branch-specific database names
- Redis database isolation
- Media file isolation

#### 5.3 Security Configuration
- Hostname validation
- CORS configuration
- SSL certificate management

### Phase 6: Testing and Validation
**Goal**: Ensure robust functionality across all scenarios

#### 6.1 Single Worktree Testing
- Create, start, stop, delete single worktree
- Verify data isolation
- Test dynamic routing

#### 6.2 Multiple Worktree Testing
- Concurrent worktree management
- Port conflict resolution
- Volume isolation verification

#### 6.3 Error Scenario Testing
- Network failures
- Volume copy failures
- Container conflicts
- Cleanup validation

#### 6.4 Performance Testing
- Resource usage monitoring
- Volume size management
- Network performance
- Startup time optimization

## Benefits

### Development Efficiency
- **True Isolation**: Each worktree has its own database, Redis, and media storage
- **No Port Conflicts**: Services use internal networking only
- **Dynamic Routing**: Caddy automatically routes based on branch names
- **Easy Management**: Simple CLI commands for worktree lifecycle
- **Development Safety**: Test database changes, cache modifications, file uploads without affecting other worktrees
- **Complete Data Isolation**: Each worktree maintains its own copy of all data
- **No Conflicts**: Different branches can't interfere with each other
- **Data Preservation**: Each worktree maintains its own state

### Operational Benefits
- **Backup/Restore**: Can backup and restore individual worktree data
- **Easy Cleanup**: Remove worktree-specific volumes without affecting others
- **Resource Management**: Monitor and control resource usage per worktree
- **Security**: Complete isolation between worktrees
- **Volume Management**: Complete control over worktree-specific data volumes
- **Data Safety**: Test database changes, cache modifications, file uploads without affecting other worktrees

## Potential Challenges

### Resource Management
- **Resource Usage**: Multiple databases and Redis instances running simultaneously
- **Disk Space**: Each worktree maintains separate data volumes
- **Memory Usage**: Multiple container instances

### Network Complexity
- **Network Management**: External network management and cleanup
- **Service Discovery**: Caddy service discovery configuration
- **Port Management**: Dynamic port allocation

### Development Workflow
- **Learning Curve**: Understanding dockertree workflow
- **CLI Usage**: Learning new command patterns
- **Volume Management**: Understanding volume isolation

## Migration Strategy

### For Existing Development
1. **Backup current state**: Ensure all work is committed
2. **Add override file**: Create `docker-compose.dockertree.yml` (no changes to existing files)
3. **Test current setup**: Verify existing functionality works unchanged
4. **Deploy CLI tool**: Install and test worktree creation

### Rollback Plan
- **No changes to existing files**: Original `docker-compose.yml` remains unchanged
- **Simple removal**: Delete `docker-compose.dockertree.yml` to disable dockertree
- **Git worktrees**: Can be easily removed if issues arise
- **Zero impact**: Existing development workflow continues unchanged

## Next Steps

1. **Review and approve this design**
2. **Create implementation timeline**
3. **Begin with Phase 1 (Infrastructure Setup)**
4. **Test each phase before proceeding**
5. **Document CLI tool usage and best practices**
