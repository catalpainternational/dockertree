#!/usr/bin/env python3
"""
Caddy Docker Monitor Script

This script monitors Docker containers with caddy.proxy labels and dynamically
updates Caddy configuration via the admin API.
"""

import json
import time
import requests
import docker
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CaddyDockerMonitor:
    """Monitor Docker containers and update Caddy configuration."""
    
    def __init__(self, caddy_admin_url: str = "http://dockertree_caddy_proxy:2019"):
        """Initialize the monitor."""
        self.caddy_admin_url = caddy_admin_url
        self.known_containers = set()
        try:
            self.docker_client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            self.docker_client = None
    
    def get_docker_containers(self) -> List[Dict]:
        """Get Docker containers with caddy.proxy labels."""
        try:
            if not self.docker_client:
                return []
            
            containers = []
            for container in self.docker_client.containers.list(filters={'label': 'caddy.proxy'}):
                containers.append({
                    'ID': container.id,
                    'Names': container.name,
                    'Labels': container.labels
                })
            
            return containers
        except Exception as e:
            logger.error(f"Failed to get Docker containers: {e}")
            return []
    
    def get_container_labels(self, container_id: str) -> Dict[str, str]:
        """Get labels for a specific container."""
        try:
            if not self.docker_client:
                return {}
            
            container = self.docker_client.containers.get(container_id)
            return container.labels
        except Exception as e:
            logger.error(f"Failed to get labels for container {container_id}: {e}")
            return {}
    
    def get_caddy_config(self) -> Optional[Dict]:
        """Get current Caddy configuration."""
        try:
            response = requests.get(f"{self.caddy_admin_url}/config", timeout=5)
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get Caddy config: {e}")
        return None
    
    def update_caddy_config(self, config: Dict) -> bool:
        """Update Caddy configuration."""
        try:
            response = requests.post(
                f"{self.caddy_admin_url}/load",
                json=config,
                timeout=10
            )
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update Caddy config: {e}")
            return False
    
    def create_route_config(self, containers: List[Dict]) -> Dict:
        """Create Caddy configuration with routes for containers."""
        config = {
            "admin": {
                "listen": "0.0.0.0:2019",
                "enforce_origin": False,
                "origins": ["//0.0.0.0:2019"]
            },
            "apps": {
                "http": {
                    "servers": {
                        "srv0": {
                            "listen": [":80"],
                            "routes": []
                        }
                    }
                }
            }
        }
        
        routes = []
        
        # Add routes for each container (specific routes first)
        for container in containers:
            # Labels are already in the container dict from get_docker_containers
            labels = container.get('Labels', {})
            
            if 'caddy.proxy' in labels:
                domain = labels['caddy.proxy']
                target = labels.get('caddy.proxy.reverse_proxy', f"{container['Names']}:8000")
                
                route = {
                    "match": [{"host": [domain]}],
                    "handle": [{
                        "handler": "reverse_proxy",
                        "upstreams": [{"dial": target}]
                    }]
                }
                
                # Add health check if specified
                if 'caddy.proxy.health_check' in labels:
                    route["handle"][0]["health_checks"] = {
                        "active": {
                            "path": labels['caddy.proxy.health_check']
                        }
                    }
                
                routes.append(route)
                logger.info(f"Added route for {domain} -> {target}")
        
        # Add default wildcard route at the end (must be last for proper matching)
        routes.append({
            "match": [{"host": ["*"]}],
            "handle": [{
                "handler": "static_response",
                "body": "Dockertree Global Caddy Proxy Ready - No worktree found for this domain",
                "status_code": 200
            }]
        })
        
        config["apps"]["http"]["servers"]["srv0"]["routes"] = routes
        return config
    
    def validate_route_configuration(self, config: Dict, containers: List[Dict]) -> bool:
        """Validate that Caddy routes match container labels correctly."""
        try:
            routes = config.get("apps", {}).get("http", {}).get("servers", {}).get("srv0", {}).get("routes", [])
            
            # Create a mapping of domain -> expected target from container labels
            expected_routes = {}
            for container in containers:
                labels = container.get('Labels', {})
                if 'caddy.proxy' in labels:
                    domain = labels['caddy.proxy']
                    expected_target = labels.get('caddy.proxy.reverse_proxy', f"{container['Names']}:8000")
                    expected_routes[domain] = expected_target
            
            # Validate each route matches expected configuration
            for route in routes:
                if 'match' in route and 'handle' in route:
                    hosts = route['match'][0].get('host', [])
                    for host in hosts:
                        if host in expected_routes:
                            # Check if the upstream target matches expected
                            handle = route['handle'][0]
                            if 'upstreams' in handle:
                                actual_target = handle['upstreams'][0].get('dial', '')
                                expected_target = expected_routes[host]
                                
                                if actual_target != expected_target:
                                    logger.error(f"Route misconfiguration detected: {host} -> {actual_target} (expected: {expected_target})")
                                    return False
                                else:
                                    logger.info(f"Route validation passed: {host} -> {actual_target}")
            
            logger.info("All route configurations validated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Route validation failed: {e}")
            return False

    def detect_configuration_drift(self, containers: List[Dict]) -> List[str]:
        """Detect when Caddy configuration doesn't match container labels."""
        drift_issues = []
        
        try:
            # Get current Caddy configuration
            response = requests.get(f"{self.caddy_admin_url}/config/", timeout=5)
            if response.status_code != 200:
                logger.warning("Could not get current Caddy configuration for drift detection")
                return drift_issues
            
            current_config = response.json()
            current_routes = current_config.get("apps", {}).get("http", {}).get("servers", {}).get("srv0", {}).get("routes", [])
            
            # Create expected routes from container labels
            expected_routes = {}
            for container in containers:
                labels = container.get('Labels', {})
                if 'caddy.proxy' in labels:
                    domain = labels['caddy.proxy']
                    expected_target = labels.get('caddy.proxy.reverse_proxy', f"{container['Names']}:8000")
                    expected_routes[domain] = expected_target
            
            # Check for drift
            for route in current_routes:
                if 'match' in route and 'handle' in route:
                    hosts = route['match'][0].get('host', [])
                    for host in hosts:
                        if host in expected_routes:
                            handle = route['handle'][0]
                            if 'upstreams' in handle:
                                actual_target = handle['upstreams'][0].get('dial', '')
                                expected_target = expected_routes[host]
                                
                                if actual_target != expected_target:
                                    drift_issues.append(f"Domain {host} points to {actual_target} but should point to {expected_target}")
            
            if drift_issues:
                logger.warning(f"Detected {len(drift_issues)} configuration drift issues")
                for issue in drift_issues:
                    logger.warning(f"  - {issue}")
            else:
                logger.info("No configuration drift detected")
                
        except Exception as e:
            logger.error(f"Configuration drift detection failed: {e}")
            drift_issues.append(f"Detection error: {e}")
        
        return drift_issues

    def auto_reconfigure_on_drift(self, containers: List[Dict]) -> bool:
        """Automatically reconfigure when drift is detected."""
        try:
            logger.info("Auto-reconfiguring due to detected drift...")
            
            # Create new configuration
            config = self.create_route_config(containers)
            
            # Validate before applying
            if not self.validate_route_configuration(config, containers):
                logger.error("Route validation failed during auto-reconfiguration")
                return False
            
            # Update Caddy
            if self.update_caddy_config(config):
                logger.info("Auto-reconfiguration completed successfully")
                return True
            else:
                logger.error("Auto-reconfiguration failed")
                return False
                
        except Exception as e:
            logger.error(f"Auto-reconfiguration failed: {e}")
            return False

    def monitor(self):
        """Main monitoring loop."""
        logger.info("Starting Caddy Docker monitor...")
        
        while True:
            try:
                containers = self.get_docker_containers()
                current_containers = {c['ID'] for c in containers}
                
                # Check if configuration needs updating
                if current_containers != self.known_containers:
                    logger.info(f"Container change detected: {len(containers)} containers")
                    
                    # Create new configuration
                    config = self.create_route_config(containers)
                    
                    # Validate configuration before applying
                    if not self.validate_route_configuration(config, containers):
                        logger.error("Route validation failed - skipping configuration update")
                        time.sleep(5)
                        continue
                    
                    # Update Caddy
                    if self.update_caddy_config(config):
                        logger.info("Caddy configuration updated successfully")
                        self.known_containers = current_containers
                    else:
                        logger.error("Failed to update Caddy configuration")
                else:
                    # Check for configuration drift even when containers haven't changed
                    drift_issues = self.detect_configuration_drift(containers)
                    if drift_issues:
                        logger.warning("Configuration drift detected, auto-reconfiguring...")
                        if self.auto_reconfigure_on_drift(containers):
                            logger.info("Auto-reconfiguration completed")
                        else:
                            logger.error("Auto-reconfiguration failed")
                
                time.sleep(5)  # Check every 5 seconds
                
            except KeyboardInterrupt:
                logger.info("Monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(5)

if __name__ == "__main__":
    monitor = CaddyDockerMonitor()
    monitor.monitor()
