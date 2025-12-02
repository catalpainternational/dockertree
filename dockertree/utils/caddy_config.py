"""
Shared Caddy configuration utility for dockertree.

This module provides a single source of truth for Caddy label and network
configuration logic, used by SetupManager, EnvironmentManager, and PackageManager.
"""

from typing import Optional, Dict, Any, List
from ..utils.logging import log_info, log_warning


# Web service names that should get Caddy labels
WEB_SERVICE_NAMES = ['web', 'app', 'frontend', 'api']

# Default port for web services
DEFAULT_WEB_PORT = 8000


def ensure_caddy_labels_and_network(
    compose_data: Dict[str, Any],
    domain: Optional[str] = None,
    ip: Optional[str] = None,
    use_localhost_pattern: bool = True
) -> bool:
    """
    Ensure Caddy labels and network are configured for web services.
    
    This is the single source of truth for Caddy configuration logic.
    Used by:
    - SetupManager._transform_compose_file() - during project setup
    - EnvironmentManager.apply_domain_overrides() - during domain override
    - PackageManager._standalone_import() - during package import
    
    Args:
        compose_data: Docker Compose data structure (dict with 'services' key)
        domain: Optional domain override (e.g., "example.com")
        ip: Optional IP override (e.g., "192.168.1.1")
        use_localhost_pattern: If True and no domain/IP, use ${COMPOSE_PROJECT_NAME}.localhost
    
    Returns:
        True if any changes were made, False otherwise
    """
    if not compose_data or 'services' not in compose_data:
        return False
    
    updated = False
    
    for service_name, service_config in compose_data['services'].items():
        # Only configure web services
        if service_name not in WEB_SERVICE_NAMES:
            continue
        
        # Determine proxy domain
        if domain:
            proxy_domain = domain
            log_info(f"Using production domain for {service_name}: {domain}")
        elif ip:
            proxy_domain = ip
            log_warning("IP deployments are HTTP-only. Let's Encrypt requires a domain name.")
        elif use_localhost_pattern:
            proxy_domain = "${COMPOSE_PROJECT_NAME}.localhost"
        else:
            # Skip if no domain/IP and localhost pattern disabled
            continue
        
        # Ensure labels list exists
        existing_labels = service_config.setdefault('labels', [])
        
        # Normalize labels to list format if it's a dict
        if isinstance(existing_labels, dict):
            existing_labels = [f"{k}={v}" for k, v in existing_labels.items()]
            service_config['labels'] = existing_labels
        
        # Build new labels
        new_labels = [
            f"caddy.proxy={proxy_domain}",
            f"caddy.proxy.reverse_proxy=${{COMPOSE_PROJECT_NAME}}-{service_name}:{DEFAULT_WEB_PORT}"
            # Note: Health check disabled by default. Add manually if needed:
            # "caddy.proxy.health_check=/health-check/"
        ]
        
        # Add labels that don't already exist
        for label in new_labels:
            label_key = label.split('=')[0] if '=' in label else label
            # Check if label already exists (by key)
            label_exists = any(
                existing_label.startswith(label_key + '=') or existing_label == label_key
                for existing_label in existing_labels
            )
            if not label_exists:
                existing_labels.append(label)
                updated = True
                log_info(f"Added Caddy label to {service_name}: {label}")
        
        # Connect web services to dockertree_caddy_proxy network
        networks = service_config.setdefault('networks', [])
        
        # Normalize networks to list format if it's a dict
        if isinstance(networks, dict):
            networks = list(networks.keys())
            service_config['networks'] = networks
        
        if 'dockertree_caddy_proxy' not in networks:
            networks.append('dockertree_caddy_proxy')
            updated = True
            log_info(f"Added dockertree_caddy_proxy network to {service_name}")
    
    return updated


def update_allowed_hosts_in_compose(
    service_config: Dict[str, Any],
    domain: str
) -> bool:
    """
    Update ALLOWED_HOSTS in docker-compose.yml environment section.
    
    Sets ALLOWED_HOSTS with domain, wildcard domain, and container names.
    
    Args:
        service_config: Service configuration from docker-compose.yml
        domain: Domain to add to ALLOWED_HOSTS
    
    Returns:
        True if ALLOWED_HOSTS was updated, False otherwise
    """
    if 'environment' not in service_config:
        return False
    
    # Build complete ALLOWED_HOSTS value with domain, wildcard, and container names
    base_domain = domain.split('.', 1)[1] if '.' in domain else domain
    allowed_hosts = f"localhost,127.0.0.1,{domain},*.{base_domain},web"
    
    # Try to get container name from COMPOSE_PROJECT_NAME if available
    # This allows adding container-specific hostnames
    try:
        from ..config.settings import build_allowed_hosts_with_container
        # Try to extract branch name from domain or service config
        # For now, use the simple format - container names will be added if COMPOSE_PROJECT_NAME is available
        env_vars = service_config['environment']
        compose_project_name = None
        
        if isinstance(env_vars, dict):
            compose_project_name = env_vars.get('COMPOSE_PROJECT_NAME', '')
        elif isinstance(env_vars, list):
            for env_var in env_vars:
                if isinstance(env_var, str) and env_var.startswith('COMPOSE_PROJECT_NAME='):
                    compose_project_name = env_var.split('=', 1)[1].strip().strip('"\'')
                    break
        
        # If we have COMPOSE_PROJECT_NAME, try to extract branch name and build full allowed hosts
        if compose_project_name and '-' in compose_project_name:
            branch_name = compose_project_name.rsplit('-', 1)[1]
            allowed_hosts = build_allowed_hosts_with_container(branch_name, [domain, f"*.{base_domain}"])
    except Exception:
        pass  # Use simple format if extraction fails
    
    env_vars = service_config['environment']
    updated = False
    
    # Handle list format: ["ALLOWED_HOSTS=localhost,127.0.0.1", "DEBUG=True"]
    if isinstance(env_vars, list):
        for i, env_var in enumerate(env_vars):
            if isinstance(env_var, str) and env_var.startswith('ALLOWED_HOSTS='):
                # Replace existing ALLOWED_HOSTS with complete value
                env_vars[i] = f"ALLOWED_HOSTS={allowed_hosts}"
                updated = True
                log_info(f"Updated ALLOWED_HOSTS in compose environment: {allowed_hosts}")
                break
        else:
            # Add ALLOWED_HOSTS if it doesn't exist
            env_vars.append(f"ALLOWED_HOSTS={allowed_hosts}")
            updated = True
            log_info(f"Added ALLOWED_HOSTS to compose environment: {allowed_hosts}")
    
    # Handle dict format: {"ALLOWED_HOSTS": "localhost,127.0.0.1", "DEBUG": "True"}
    elif isinstance(env_vars, dict):
        env_vars['ALLOWED_HOSTS'] = allowed_hosts
        updated = True
        log_info(f"Updated ALLOWED_HOSTS in compose environment: {allowed_hosts}")
    
    return updated



