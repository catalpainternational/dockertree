# Dockertree User Guide

This directory contains the dockertree configuration for your project. This guide is optimized for coding agents and developers working with dockertree environments.

## 🚀 Quick Reference

### Essential Commands

```bash
# Worktree Management
dockertree create <branch-name>     # Create new worktree
dockertree <branch-name> up -d      # Start worktree environment
dockertree <branch-name> down       # Stop worktree environment
dockertree <branch-name> remove     # Remove worktree (keep branch)
dockertree <branch-name> delete     # Delete worktree and branch

# Docker Compose Integration
dockertree <branch-name> exec <service> <command>    # Execute command in container
dockertree <branch-name> logs <service>              # View container logs
dockertree <branch-name> ps                          # List containers
dockertree <branch-name> run <service> <command>     # Run one-off command
```

### For Coding Agents

**Key Pattern**: Use `dockertree <worktree-name> <docker-compose-command>` for all container operations.

**Common Tasks**:
```bash
# Django Management
dockertree feature-auth exec web python manage.py migrate
dockertree feature-auth exec web python manage.py collectstatic
dockertree feature-auth exec web python manage.py test

# Database Operations
dockertree feature-auth exec web python manage.py shell
dockertree feature-auth exec web python manage.py dbshell

# Application Logs
dockertree feature-auth logs web
dockertree feature-auth logs -f web  # Follow logs

# Container Management
dockertree feature-auth ps
dockertree feature-auth restart web
dockertree feature-auth run --rm web bash
```

## 📁 Directory Structure

```
.dockertree/
├── README.md                    # This file
├── config.yml                   # Project configuration
├── docker-compose.worktree.yml  # Docker Compose override file
├── env.dockertree             # Environment variables for worktree
└── worktrees/                  # Worktree directories
    ├── feature-auth/
    ├── feature-payments/
    └── test-branch/
```

## 🔧 Configuration Files

### `config.yml`
Main project configuration including:
- Project name
- Caddy network settings
- Service container name templates
- Volume configurations
- Environment variables

### `docker-compose.worktree.yml`
Docker Compose override file that:
- Extends your main `docker-compose.yml`
- Adds worktree-specific configurations
- Sets up isolated volumes and networks
- Configures Caddy routing

### `env.dockertree`
Environment variables for each worktree:
- `COMPOSE_PROJECT_NAME`: Unique project name per worktree
- `PROJECT_ROOT`: Path to worktree directory
- `SITE_DOMAIN`: Unique domain for the worktree
- `ALLOWED_HOSTS`: Django allowed hosts configuration

## 🌐 Accessing Your Applications

Each worktree gets its own domain:
- **Pattern**: `{project-name}-{branch-name}.localhost`
- **Example**: `myapp-feature-auth.localhost`

### Common Service Names
- `web` - Main web application (Django, Flask, etc.)
- `db` - Database service (PostgreSQL, MySQL)
- `redis` - Cache service
- `nginx` - Web server (if used)

## 🛠️ Development Workflow

### 1. Create and Start Worktree
```bash
# Create new worktree
dockertree create feature-new-auth

# Start the environment
dockertree feature-new-auth up -d

# Access the application
open http://myapp-feature-new-auth.localhost
```

### 2. Development Tasks
```bash
# Run migrations
dockertree feature-new-auth exec web python manage.py migrate

# Install new packages
dockertree feature-new-auth exec web pip install new-package

# Run tests
dockertree feature-new-auth run --rm web python manage.py test

# Check logs
dockertree feature-new-auth logs web
```

### 3. Clean Up
```bash
# Stop environment
dockertree feature-new-auth down

# Remove worktree (keeps git branch)
dockertree feature-new-auth remove

# Or delete completely (removes git branch)
dockertree feature-new-auth delete
```

## 🔍 Troubleshooting

### Common Issues

**Worktree not found**:
```bash
# Check existing worktrees
dockertree list

# Create if needed
dockertree create <branch-name>
```

**Container not running**:
```bash
# Check container status
dockertree <branch-name> ps

# View logs
dockertree <branch-name> logs web

# Restart if needed
dockertree <branch-name> restart web
```

**Database issues**:
```bash
# Check database container
dockertree <branch-name> exec db psql -U user -d database

# Run migrations
dockertree <branch-name> exec web python manage.py migrate
```

### Debug Commands

```bash
# Check worktree status
dockertree list

# Check container status
dockertree <branch-name> ps

# View all logs
dockertree <branch-name> logs

# Check environment variables
dockertree <branch-name> exec web env | grep COMPOSE
```

## 📊 Volume Management

Each worktree has isolated volumes:
- `{project}-{branch}_postgres_data` - Database data
- `{project}-{branch}_redis_data` - Cache data
- `{project}-{branch}_media_files` - User uploads

### Volume Operations
```bash
# List volumes
dockertree volumes list

# Check volume sizes
dockertree volumes size

# Backup volumes
dockertree volumes backup <branch-name>

# Clean up volumes
dockertree volumes clean <branch-name>
```

## 🚀 Advanced Usage

### Multiple Worktrees
```bash
# Work on multiple features simultaneously
dockertree create feature-auth
dockertree create feature-payments
dockertree create feature-notifications

# Start all
dockertree feature-auth up -d
dockertree feature-payments up -d
dockertree feature-notifications up -d

# Access each independently
open http://myapp-feature-auth.localhost
open http://myapp-feature-payments.localhost
open http://myapp-feature-notifications.localhost
```

### Bulk Operations
```bash
# Remove all worktrees (keeps branches)
dockertree remove-all

# Delete all worktrees and branches
dockertree delete-all --force

# Remove by pattern
dockertree remove test-*
dockertree delete feature-*
```

### Custom Environment
```bash
# Edit worktree environment
vim worktrees/<branch-name>/.dockertree/env.dockertree

# Restart to apply changes
dockertree <branch-name> down
dockertree <branch-name> up -d
```

## 🎯 For Coding Agents

### Key Patterns to Remember

1. **Always use worktree name first**: `dockertree <worktree-name> <command>`
2. **Docker compose commands work directly**: `dockertree <worktree-name> exec web <command>`
3. **Each worktree is isolated**: Changes in one worktree don't affect others
4. **Use `exec` for interactive commands**: `dockertree <worktree-name> exec web bash`
5. **Use `run` for one-off commands**: `dockertree <worktree-name> run --rm web <command>`

### Common Django Tasks
```bash
# Database operations
dockertree <branch> exec web python manage.py migrate
dockertree <branch> exec web python manage.py makemigrations
dockertree <branch> exec web python manage.py shell

# Static files
dockertree <branch> exec web python manage.py collectstatic

# Testing
dockertree <branch> run --rm web python manage.py test
dockertree <branch> run --rm web python manage.py test app.tests

# Package management
dockertree <branch> exec web pip install package-name
dockertree <branch> exec web pip freeze > requirements.txt
```

### Service Discovery
```bash
# List available services
dockertree <branch> ps

# Common service names: web, db, redis, nginx
# Use these in exec/run commands
```

---

**Need Help?** Run `dockertree --help` for full command reference.
