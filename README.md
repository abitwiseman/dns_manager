# DNS Server Management API

Python API for managing DNS servers (BIND and dnsmasq) on CentOS systems. The API provides functionality to install, configure, and manage DNS servers and zones.

## Features

### BIND (Named) Server Management
- Server installation and configuration
- Zone management (A, CNAME records)
- Reverse zone (PTR records) support
- Zone file validation
- SELinux context handling
- Service management

### dnsmasq Server Management
- Server installation and configuration
- Upstream DNS configuration
- Cache size management
- Service control

## Dependencies

- Python 3.6+
- paramiko
- CentOS/RHEL system

## Installation

```bash
pip install paramiko
```

## Usage

### Initialize Servers

```python
from dns_api import NamedServer, DnsmasqServer, SSHClient

# Setup SSH connection
ssh = SSHClient(
    hostname="server1.example.com",
    username="root",
    password="password"  # or use key_filename for SSH key
)
ssh.connect()

# Initialize BIND server
named_server = NamedServer(ssh)

# Initialize dnsmasq server
dnsmasq_server = DnsmasqServer(ssh)
```

### Configure BIND Server

```python
# Basic BIND configuration
config = {
    "forwarder": "8.8.8.8"
}
named_server.configure(config)

# Add forward zone
zone_config = {
    "type": "master",
    "records": [
        {"name": "@", "type": "A", "value": "192.168.1.10"},
        {"name": "www", "type": "A", "value": "192.168.1.10"},
        {"name": "mail", "type": "A", "value": "192.168.1.11"},
        {"name": "webmail", "type": "CNAME", "value": "mail"}
    ]
}
named_server.add_zone("example.com", zone_config)

# Add PTR zone
ptr_config = {
    "records": [
        {"ip": "192.168.1.10", "hostname": "www.example.com"},
        {"ip": "192.168.1.11", "hostname": "mail.example.com"}
    ]
}
named_server.add_ptr_zone("192.168.1.0/24", ptr_config)
```

### Configure dnsmasq

```python
# Configure dnsmasq with upstream DNS
config = {
    "upstream_dns": "8.8.8.8",
    "cache_size": 0
}
dnsmasq_server.configure(config)
```

### Delete Zone

```python
# Delete a zone
named_server.delete_zone("example.com")
```

## Error Handling

The API uses the `DNSConfigError` exception for error handling:

```python
try:
    named_server.configure(config)
except DNSConfigError as e:
    print(f"Configuration failed: {str(e)}")
```

## Notes

- All operations require root/sudo access on the target server
- Automatic backup of existing configurations
- SELinux context is handled automatically
- Supports CentOS/RHEL systems
- Configuration validation before applying changes

## License

MIT License