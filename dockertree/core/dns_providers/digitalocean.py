"""
Digital Ocean DNS provider implementation.

This module provides DNS management via Digital Ocean's DNS API v2.
API Documentation: https://docs.digitalocean.com/reference/api/api-reference/#tag/Domains
"""

import requests
import time
import socket
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from ..dns_manager import DNSProvider
from ..droplet_manager import DropletProvider, DropletInfo
from ...utils.logging import log_info, log_warning, log_error


class DigitalOceanProvider(DNSProvider, DropletProvider):
    """Digital Ocean DNS and Droplet provider implementation."""
    
    API_BASE_URL = "https://api.digitalocean.com/v2"
    
    def __init__(self, api_token: str):
        """Initialize Digital Ocean provider.
        
        Args:
            api_token: Digital Ocean API token
        """
        self.api_token = api_token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        })
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        """Make API request with error handling.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint
            **kwargs: Additional request arguments
            
        Returns:
            Response object or None if failed
        """
        url = f"{self.API_BASE_URL}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=10, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                log_error("Digital Ocean API authentication failed. Check your API token.")
            elif e.response.status_code == 404:
                log_warning(f"Domain not found: {endpoint}")
            else:
                log_error(f"Digital Ocean API error: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            log_error(f"Digital Ocean API request failed: {e}")
            return None
    
    def check_domain_exists(self, subdomain: str, domain: str) -> Tuple[bool, Optional[str]]:
        """Check if subdomain exists and return current IP if any.
        
        Args:
            subdomain: Subdomain name (e.g., 'app')
            domain: Base domain (e.g., 'example.com')
            
        Returns:
            Tuple of (exists, current_ip). current_ip is None if doesn't exist.
        """
        response = self._make_request('GET', f'/domains/{domain}/records')
        if not response:
            return False, None
        
        try:
            data = response.json()
            records = data.get('domain_records', [])
            
            full_name = f"{subdomain}.{domain}" if subdomain else domain
            
            for record in records:
                if record.get('type') == 'A' and record.get('name') == subdomain:
                    ip = record.get('data')
                    log_info(f"Found existing A record for {full_name}: {ip}")
                    return True, ip
            
            log_info(f"No A record found for {full_name}")
            return False, None
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing Digital Ocean API response: {e}")
            return False, None
    
    def create_subdomain(self, subdomain: str, domain: str, ip: str) -> bool:
        """Create A record for subdomain pointing to IP.
        
        Args:
            subdomain: Subdomain name (e.g., 'app')
            domain: Base domain (e.g., 'example.com')
            ip: IP address to point to
            
        Returns:
            True if successful, False otherwise
        """
        payload = {
            'type': 'A',
            'name': subdomain,
            'data': ip,
            'ttl': 3600
        }
        
        response = self._make_request('POST', f'/domains/{domain}/records', json=payload)
        if not response:
            return False
        
        log_info(f"Successfully created A record: {subdomain}.{domain} -> {ip}")
        return True
    
    def list_subdomains(self, domain: str) -> List[str]:
        """List all subdomains for a domain.
        
        Args:
            domain: Base domain (e.g., 'example.com')
            
        Returns:
            List of subdomain names
        """
        response = self._make_request('GET', f'/domains/{domain}/records')
        if not response:
            return []
        
        try:
            data = response.json()
            records = data.get('domain_records', [])
            
            subdomains = []
            for record in records:
                if record.get('type') == 'A' and record.get('name'):
                    subdomains.append(record.get('name'))
            
            return subdomains
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing Digital Ocean API response: {e}")
            return []
    
    def list_all_domains(self) -> List[str]:
        """List all base domains in the account.
        
        Returns:
            List of base domain names
        """
        response = self._make_request('GET', '/domains')
        if not response:
            return []
        
        try:
            data = response.json()
            domains = data.get('domains', [])
            return [d.get('name') for d in domains if d.get('name')]
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing Digital Ocean API response: {e}")
            return []
    
    def update_subdomain(self, subdomain: str, domain: str, ip: str) -> bool:
        """Update A record for subdomain to point to new IP.
        
        Args:
            subdomain: Subdomain name (e.g., 'app')
            domain: Base domain (e.g., 'example.com')
            ip: New IP address to point to
            
        Returns:
            True if successful, False otherwise
        """
        # First, get all records to find the record ID
        response = self._make_request('GET', f'/domains/{domain}/records')
        if not response:
            log_error(f"Failed to retrieve DNS records for {domain}")
            return False
        
        try:
            data = response.json()
            records = data.get('domain_records', [])
            
            # Find the A record matching the subdomain
            record_id = None
            for record in records:
                if record.get('type') == 'A' and record.get('name') == subdomain:
                    record_id = record.get('id')
                    break
            
            if not record_id:
                log_warning(f"No A record found for {subdomain}.{domain}")
                return False
            
            # Update the record
            payload = {
                'data': ip,
                'ttl': 3600
            }
            update_response = self._make_request('PUT', f'/domains/{domain}/records/{record_id}', json=payload)
            if not update_response:
                log_error(f"Failed to update DNS record for {subdomain}.{domain}")
                return False
            
            log_info(f"Successfully updated A record: {subdomain}.{domain} -> {ip}")
            return True
            
        except (KeyError, ValueError) as e:
            log_error(f"Error parsing Digital Ocean API response: {e}")
            return False
    
    def delete_subdomain(self, subdomain: str, domain: str) -> bool:
        """Delete A record for subdomain.
        
        Args:
            subdomain: Subdomain name (e.g., 'app')
            domain: Base domain (e.g., 'example.com')
            
        Returns:
            True if successful, False otherwise
        """
        # First, get all records to find the record ID
        response = self._make_request('GET', f'/domains/{domain}/records')
        if not response:
            log_error(f"Failed to retrieve DNS records for {domain}")
            return False
        
        try:
            data = response.json()
            records = data.get('domain_records', [])
            
            # Find the A record matching the subdomain
            record_id = None
            for record in records:
                if record.get('type') == 'A' and record.get('name') == subdomain:
                    record_id = record.get('id')
                    break
            
            if not record_id:
                log_warning(f"No A record found for {subdomain}.{domain}")
                return False
            
            # Delete the record
            delete_response = self._make_request('DELETE', f'/domains/{domain}/records/{record_id}')
            if not delete_response:
                log_error(f"Failed to delete DNS record for {subdomain}.{domain}")
                return False
            
            log_info(f"Successfully deleted A record: {subdomain}.{domain}")
            return True
            
        except (KeyError, ValueError) as e:
            log_error(f"Error parsing Digital Ocean API response: {e}")
            return False
    
    def find_dns_records_by_ip(self, ip: str, domain: Optional[str] = None) -> List[Tuple[str, str, int]]:
        """Find DNS A records pointing to a specific IP address.
        
        Args:
            ip: IP address to search for
            domain: Optional domain to limit search (if None, searches all domains)
            
        Returns:
            List of tuples: (subdomain, domain, record_id)
        """
        results = []
        
        try:
            if domain:
                # Search only in specified domain
                domains_to_search = [domain]
            else:
                # Get all domains in the account
                domains_response = self._make_request('GET', '/domains')
                if not domains_response:
                    log_warning("Failed to retrieve domains list")
                    return results
                
                domains_data = domains_response.json()
                domains_to_search = [d.get('name') for d in domains_data.get('domains', [])]
            
            # Search each domain for A records pointing to the IP
            for search_domain in domains_to_search:
                records_response = self._make_request('GET', f'/domains/{search_domain}/records')
                if not records_response:
                    continue
                
                try:
                    records_data = records_response.json()
                    records = records_data.get('domain_records', [])
                    
                    for record in records:
                        if (record.get('type') == 'A' and 
                            record.get('data') == ip):
                            subdomain = record.get('name', '')
                            record_id = record.get('id')
                            if record_id:
                                results.append((subdomain, search_domain, record_id))
                except (KeyError, ValueError) as e:
                    log_warning(f"Error parsing records for {search_domain}: {e}")
                    continue
            
            return results
            
        except Exception as e:
            log_error(f"Error finding DNS records by IP: {e}")
            return results
    
    def list_ssh_keys(self) -> List[Dict[str, Any]]:
        """List all SSH keys from Digital Ocean account.
        
        Returns:
            List of dictionaries with keys: id, name, fingerprint, public_key
        """
        response = self._make_request('GET', '/account/keys')
        if not response:
            return []
        
        try:
            data = response.json()
            return data.get('ssh_keys', [])
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing SSH keys response: {e}")
            return []

    def resolve_ssh_key(self, key_name: str) -> Optional[int]:
        """Resolve SSH key name to key ID.
        
        Accepts only SSH key names (e.g., "anders", "peter").
        Numeric IDs and fingerprints are not supported.
        
        Args:
            key_name: SSH key name (case-insensitive)
            
        Returns:
            SSH key ID (integer) if found, None otherwise
        """
        # List all SSH keys
        ssh_keys = self.list_ssh_keys()
        
        for key in ssh_keys:
            # Check by name (case-insensitive)
            if key.get('name', '').lower() == key_name.lower():
                return key.get('id')
        
        return None
    
    # Droplet Provider Methods
    
    def create_droplet(self, name: str, region: str, size: str, image: str,
                      ssh_keys: Optional[List[str]] = None,
                      tags: Optional[List[str]] = None) -> Optional[DropletInfo]:
        """Create a new droplet.
        
        Args:
            name: Droplet name
            region: Droplet region (e.g., 'nyc1')
            size: Droplet size (e.g., 's-1vcpu-1gb')
            image: Droplet image (e.g., 'ubuntu-22-04-x64')
            ssh_keys: List of SSH key names (e.g., ['anders', 'peter']) - will be resolved to IDs
            tags: List of tags for the droplet
            
        Returns:
            DropletInfo if successful, None otherwise
        """
        payload = {
            'name': name,
            'region': region,
            'size': size,
            'image': image
        }
        
        if ssh_keys:
            # Resolve SSH key names to IDs
            resolved_keys = []
            for key_name in ssh_keys:
                key_id = self.resolve_ssh_key(key_name)
                if key_id:
                    resolved_keys.append(key_id)
                    log_info(f"Resolved SSH key '{key_name}' to ID: {key_id}")
                else:
                    log_warning(f"SSH key '{key_name}' not found. Skipping.")
            
            if resolved_keys:
                payload['ssh_keys'] = resolved_keys
                log_info(f"Using SSH keys: {', '.join(map(str, resolved_keys))}")
            else:
                log_warning("No valid SSH keys found. Droplet will be created without SSH keys.")
        
        if tags:
            payload['tags'] = tags
        
        response = self._make_request('POST', '/droplets', json=payload)
        if not response:
            return None
        
        try:
            data = response.json()
            droplet_data = data.get('droplet', {})
            
            droplet_id = droplet_data.get('id')
            droplet_name = droplet_data.get('name')
            droplet_status = droplet_data.get('status', 'new')
            droplet_region = droplet_data.get('region', {}).get('slug', region)
            droplet_size = droplet_data.get('size_slug', size)
            droplet_image = droplet_data.get('image', {}).get('slug', image)
            droplet_tags = droplet_data.get('tags', tags or [])
            
            # Extract IP address from networks
            ip_address = None
            networks = droplet_data.get('networks', {})
            v4_networks = networks.get('v4', [])
            for network in v4_networks:
                if network.get('type') == 'public':
                    ip_address = network.get('ip_address')
                    break
            
            # Parse created_at if available
            created_at = None
            if 'created_at' in droplet_data:
                try:
                    created_at = datetime.fromisoformat(droplet_data['created_at'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass
            
            log_info(f"Successfully created droplet: {name} (ID: {droplet_id})")
            
            return DropletInfo(
                id=droplet_id,
                name=droplet_name,
                ip_address=ip_address,
                status=droplet_status,
                region=droplet_region,
                size=droplet_size,
                image=droplet_image,
                created_at=created_at,
                tags=droplet_tags
            )
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing droplet creation response: {e}")
            return None
    
    def list_droplets(self) -> List[DropletInfo]:
        """List all droplets.
        
        Returns:
            List of DropletInfo objects
        """
        response = self._make_request('GET', '/droplets')
        if not response:
            return []
        
        try:
            data = response.json()
            droplets_data = data.get('droplets', [])
            
            droplets = []
            for droplet_data in droplets_data:
                droplet_id = droplet_data.get('id')
                droplet_name = droplet_data.get('name')
                droplet_status = droplet_data.get('status', 'unknown')
                droplet_region = droplet_data.get('region', {}).get('slug', 'unknown')
                droplet_size = droplet_data.get('size_slug', 'unknown')
                droplet_image = droplet_data.get('image', {}).get('slug', 'unknown')
                droplet_tags = droplet_data.get('tags', [])
                
                # Extract IP address from networks
                ip_address = None
                networks = droplet_data.get('networks', {})
                v4_networks = networks.get('v4', [])
                for network in v4_networks:
                    if network.get('type') == 'public':
                        ip_address = network.get('ip_address')
                        break
                
                # Parse created_at if available
                created_at = None
                if 'created_at' in droplet_data:
                    try:
                        created_at = datetime.fromisoformat(droplet_data['created_at'].replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass
                
                droplets.append(DropletInfo(
                    id=droplet_id,
                    name=droplet_name,
                    ip_address=ip_address,
                    status=droplet_status,
                    region=droplet_region,
                    size=droplet_size,
                    image=droplet_image,
                    created_at=created_at,
                    tags=droplet_tags
                ))
            
            return droplets
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing droplets list response: {e}")
            return []
    
    def get_droplet(self, droplet_id: int) -> Optional[DropletInfo]:
        """Get droplet information by ID.
        
        Args:
            droplet_id: Droplet ID
            
        Returns:
            DropletInfo if found, None otherwise
        """
        response = self._make_request('GET', f'/droplets/{droplet_id}')
        if not response:
            return None
        
        try:
            data = response.json()
            droplet_data = data.get('droplet', {})
            
            droplet_name = droplet_data.get('name')
            droplet_status = droplet_data.get('status', 'unknown')
            droplet_region = droplet_data.get('region', {}).get('slug', 'unknown')
            droplet_size = droplet_data.get('size_slug', 'unknown')
            droplet_image = droplet_data.get('image', {}).get('slug', 'unknown')
            droplet_tags = droplet_data.get('tags', [])
            
            # Extract IP address from networks
            ip_address = None
            networks = droplet_data.get('networks', {})
            v4_networks = networks.get('v4', [])
            for network in v4_networks:
                if network.get('type') == 'public':
                    ip_address = network.get('ip_address')
                    break
            
            # Parse created_at if available
            created_at = None
            if 'created_at' in droplet_data:
                try:
                    created_at = datetime.fromisoformat(droplet_data['created_at'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass
            
            return DropletInfo(
                id=droplet_id,
                name=droplet_name,
                ip_address=ip_address,
                status=droplet_status,
                region=droplet_region,
                size=droplet_size,
                image=droplet_image,
                created_at=created_at,
                tags=droplet_tags
            )
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing droplet info response: {e}")
            return None
    
    def destroy_droplet(self, droplet_id: int) -> bool:
        """Destroy a droplet.
        
        Args:
            droplet_id: Droplet ID to destroy
            
        Returns:
            True if successful, False otherwise
        """
        response = self._make_request('DELETE', f'/droplets/{droplet_id}')
        if not response:
            return False
        
        log_info(f"Successfully destroyed droplet: {droplet_id}")
        return True
    
    def _check_ssh_ready(self, ip_address: str, timeout: int = 5) -> bool:
        """Check if SSH is accessible on the droplet.
        
        Args:
            ip_address: Droplet IP address
            timeout: Connection timeout in seconds
            
        Returns:
            True if SSH is accessible, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip_address, 22))
            sock.close()
            return result == 0
        except Exception:
            return False

    def wait_for_droplet_ready(self, droplet_id: int, timeout: int = 300, check_ssh: bool = True) -> bool:
        """Wait for droplet to be ready (active status and optionally SSH).
        
        Args:
            droplet_id: Droplet ID
            timeout: Maximum time to wait in seconds (default: 300)
            check_ssh: Also wait for SSH to be accessible (default: True)
            
        Returns:
            True if droplet is ready, False if timeout
        """
        start_time = time.time()
        log_info(f"Waiting for droplet {droplet_id} to be ready...")
        
        droplet = None
        ssh_ready = False
        while time.time() - start_time < timeout:
            droplet = self.get_droplet(droplet_id)
            if not droplet:
                log_warning(f"Droplet {droplet_id} not found")
                return False
            
            if droplet.status in ['off', 'archive']:
                log_error(f"Droplet {droplet_id} is in {droplet.status} status")
                return False
            
            if droplet.status == 'active':
                # If SSH check is enabled and we have an IP, verify SSH
                if check_ssh and droplet.ip_address:
                    if self._check_ssh_ready(droplet.ip_address):
                        if not ssh_ready:
                            log_info(f"SSH is ready on {droplet.ip_address}")
                            ssh_ready = True
                        log_info(f"Droplet {droplet_id} is ready (status: {droplet.status}, SSH: ready)")
                        return True
                    # SSH not ready yet, continue waiting
                    if not ssh_ready:
                        log_info(f"Droplet is active, waiting for SSH to be ready on {droplet.ip_address}...")
                        ssh_ready = False
                else:
                    # No SSH check or no IP yet
                    log_info(f"Droplet {droplet_id} is ready (status: {droplet.status})")
                    return True
            
            # Wait a bit before checking again
            time.sleep(5)
        
        log_warning(f"Timeout waiting for droplet {droplet_id} to be ready")
        return False
    
    def list_sizes(self) -> List[Dict[str, Any]]:
        """List available droplet sizes from DigitalOcean API.
        
        Returns:
            List of dictionaries with size information:
            - slug: Size slug (e.g., 's-1vcpu-1gb')
            - memory: Memory in MB
            - vcpus: Number of vCPUs
            - disk: Disk size in GB
            - price_monthly: Monthly price in USD
            - price_hourly: Hourly price in USD
            - available: Whether size is available
        """
        response = self._make_request('GET', '/sizes')
        if not response:
            return []
        
        try:
            data = response.json()
            sizes_data = data.get('sizes', [])
            
            sizes = []
            for size_data in sizes_data:
                # Extract price information
                price_monthly = None
                price_hourly = None
                if 'price_monthly' in size_data:
                    price_monthly = size_data['price_monthly']
                if 'price_hourly' in size_data:
                    price_hourly = size_data['price_hourly']
                
                size_info = {
                    'slug': size_data.get('slug', 'unknown'),
                    'memory': size_data.get('memory', 0),
                    'vcpus': size_data.get('vcpus', 0),
                    'disk': size_data.get('disk', 0),
                    'price_monthly': price_monthly,
                    'price_hourly': price_hourly,
                    'available': size_data.get('available', False),
                    'regions': size_data.get('regions', [])
                }
                sizes.append(size_info)
            
            return sizes
        except (KeyError, ValueError) as e:
            log_warning(f"Error parsing sizes response: {e}")
            return []

