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
        # Note: We don't set caddy.proxy.reverse_proxy here because:
        # 1. Service names (web:8000) don't resolve on external networks across Compose projects
        # 2. Container name patterns (${COMPOSE_PROJECT_NAME}-web) don't match actual names (test-web-1)
        # 3. The Caddy dynamic config script automatically uses container['Names'] as fallback
        #    which gives us the actual unique container name (e.g., test-web-1:8000)
        new_labels = [
            f"caddy.proxy={proxy_domain}"
            # Note: Health check disabled by default. Add manually if needed:
            # "caddy.proxy.health_check=/health-check/"
            # Note: reverse_proxy target is auto-detected from container name by Caddy script
        ]
        
        # Add or update labels
        for label in new_labels:
            label_key = label.split('=')[0] if '=' in label else label
            # Find existing label index (if any)
            existing_index = None
            for i, existing_label in enumerate(existing_labels):
                if existing_label.startswith(label_key + '=') or existing_label == label_key:
                    existing_index = i
                    break
            
            if existing_index is not None:
                # Label exists - update it only if we have a production domain/IP
                # (don't overwrite custom labels with localhost pattern)
                if domain or ip:
                    old_value = existing_labels[existing_index]
                    existing_labels[existing_index] = label
                    updated = True
                    log_info(f"Updated Caddy label for {service_name}: {old_value} -> {label}")
                # else: keep existing label (localhost pattern shouldn't overwrite)
            else:
                # Label doesn't exist - add it
                existing_labels.append(label)
                updated = True
                log_info(f"Added Caddy label to {service_name}: {label}")
        
        # Connect web services to dockertree_caddy_proxy network
        # Important: Web containers need BOTH:
        # 1. Default network (for database/redis access)
        # 2. dockertree_caddy_proxy network (for Caddy routing)
        # When networks are explicitly specified (list or dict), Docker Compose does NOT
        # automatically add the default network. We must explicitly include it.
        if 'networks' not in service_config:
            # No networks specified - explicitly include both default and dockertree_caddy_proxy
            service_config['networks'] = {
                'default': None,  # Explicitly include default network for database access
                'dockertree_caddy_proxy': None
            }
            updated = True
            log_info(f"Added networks to {service_name}: default + dockertree_caddy_proxy")
        elif isinstance(service_config['networks'], list):
            # Convert list to dict format, preserving all existing networks
            networks_dict = {}
            for network in service_config['networks']:
                networks_dict[network] = None
            # Ensure default network is included for database access
            if 'default' not in networks_dict:
                networks_dict['default'] = None
            # Add dockertree_caddy_proxy if not present
            if 'dockertree_caddy_proxy' not in networks_dict:
                networks_dict['dockertree_caddy_proxy'] = None
                updated = True
            service_config['networks'] = networks_dict
            if updated:
                log_info(f"Added networks to {service_name}: preserved existing + default + dockertree_caddy_proxy")
        elif isinstance(service_config['networks'], dict):
            # Already in dict format - ensure both default and dockertree_caddy_proxy are present
            network_added = False
            if 'default' not in service_config['networks']:
                service_config['networks']['default'] = None
                network_added = True
            if 'dockertree_caddy_proxy' not in service_config['networks']:
                service_config['networks']['dockertree_caddy_proxy'] = None
                network_added = True
            if network_added:
                updated = True
                log_info(f"Added networks to {service_name}: ensured default + dockertree_caddy_proxy")
    
    # Ensure top-level networks declaration exists if any service references dockertree_caddy_proxy
    # This is required for Docker Compose to recognize the network as external
    network_referenced = False
    for service_name, service_config in compose_data['services'].items():
        if 'networks' in service_config:
            networks = service_config['networks']
            if isinstance(networks, dict) and 'dockertree_caddy_proxy' in networks:
                network_referenced = True
                break
            elif isinstance(networks, list) and 'dockertree_caddy_proxy' in networks:
                network_referenced = True
                break
    
    if network_referenced:
        compose_data.setdefault('networks', {})
        if 'dockertree_caddy_proxy' not in compose_data['networks']:
            compose_data['networks']['dockertree_caddy_proxy'] = {'external': True}
            updated = True
            log_info("Added top-level networks declaration for dockertree_caddy_proxy (external)")
    
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
    from ..core.dns_manager import get_base_domain
    base_domain = get_base_domain(domain)
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



