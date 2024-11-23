import paramiko
import logging
import time
import re
from typing import Dict, Optional, List
from .exceptions import DNSConfigError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SSHClient:
    def __init__(self, hostname: str, username: str, password: Optional[str] = None, key_filename: Optional[str] = None):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self):
        try:
            self.client.connect(
                self.hostname,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename
            )
        except Exception as e:
            raise DNSConfigError(f"Failed to connect to {self.hostname}: {str(e)}")

    def execute_command(self, command: str) -> tuple:
        stdin, stdout, stderr = self.client.exec_command(command)
        return stdout.read().decode(), stderr.read().decode()

    def close(self):
        self.client.close()

class NamedServer:
    def __init__(self, ssh_client: SSHClient):
        self.ssh = ssh_client
        self.named_conf = "/etc/named.conf"
        self.zones_dir = "/var/named"

    def install(self):
        """Install BIND on CentOS"""
        stdout, _ = self.ssh.execute_command("rpm -q bind")
        if "bind-" in stdout:
            logger.info("BIND is already installed")
            return

        try:
            # Install BIND
            self.ssh.execute_command("yum -y install bind bind-utils")
            
            # Enable and start service
            self.ssh.execute_command("systemctl enable named")
            self.ssh.execute_command("systemctl start named")
            
            logger.info("BIND installed successfully")
            
        except Exception as e:
            raise DNSConfigError(f"Failed to install BIND: {str(e)}")

    def configure(self, config: Dict):
        """Configure BIND"""
        try:
            # First ensure BIND is installed
            self.install()

            # Backup existing config if it exists
            self.ssh.execute_command("cp /etc/named.conf /etc/named.conf.bak 2>/dev/null || true")

            # Create basic named.conf
            named_conf_content = """
options {
        listen-on port 53 { any; };
        listen-on-v6 { none; };
        directory       "/var/named";
        dump-file       "/var/named/data/cache_dump.db";
        statistics-file "/var/named/data/named_stats.txt";
        memstatistics-file "/var/named/data/named_mem_stats.txt";
        secroots-file   "/var/named/data/named.secroots";
        recursing-file  "/var/named/data/named.recursing";
        allow-query     { any; };
        forward only;
        forwarders { %s; };
};

logging {
        channel default_debug {
                file "data/named.run";
                severity dynamic;
        };
};

zone "." IN {
        type hint;
        file "named.ca";
};
""" % config['forwarder']
            
            # Write configuration
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.named_conf, 'w') as f:
                    f.write(named_conf_content)

            logger.info("Configuration file written successfully")

            # Check named.conf syntax
            _, stderr = self.ssh.execute_command("named-checkconf")
            if stderr:
                raise DNSConfigError(f"named.conf syntax error: {stderr}")

            # Fix permissions and SELinux context
            commands = [
                "chown root:named /etc/named.conf",
                "restorecon -v /etc/named.conf",
                "chmod 640 /etc/named.conf"
            ]
            for cmd in commands:
                self.ssh.execute_command(cmd)

            # Restart named service
            self.ssh.execute_command("systemctl restart named")
            
            # Verify service is running
            stdout, _ = self.ssh.execute_command("systemctl is-active named")
            if "active" not in stdout:
                raise DNSConfigError("named failed to start after configuration")
            
            logger.info("BIND configured and running successfully")
            
        except Exception as e:
            logger.error(f"Error during configuration: {str(e)}")
            raise DNSConfigError(f"Failed to configure BIND: {str(e)}")

    def add_zone(self, zone_name: str, zone_config: Dict):
        """
        Add a new zone to BIND configuration
        
        Example zone_config:
        {
            "type": "master",
            "records": [
                {"name": "@", "type": "A", "value": "192.168.1.10"},
                {"name": "www", "type": "A", "value": "192.168.1.10"},
                {"name": "mail", "type": "A", "value": "192.168.1.11"},
                {"name": "webmail", "type": "CNAME", "value": "mail"},
                {"name": "ftp", "type": "CNAME", "value": "www"}
            ]
        }
        """
        try:
            # Create zone file content
            zone_content = f"""$TTL 86400
    @       IN      SOA     {zone_name}. admin.{zone_name}. (
                            {int(time.time())}  ; Serial
                            3600        ; Refresh
                            1800        ; Retry
                            604800      ; Expire
                            86400 )     ; Minimum TTL

    ; Name servers
    @       IN      NS      ns1.{zone_name}.
    @       IN      NS      ns2.{zone_name}.

    ; A Records and CNAME Records
    """
            # First add all A records
            for record in zone_config.get('records', []):
                if record['type'] == 'A':
                    if record['name'] == '@':
                        zone_content += f"@    IN    A    {record['value']}\n"
                    else:
                        zone_content += f"{record['name']}    IN    A    {record['value']}\n"

            # Then add CNAME records
            for record in zone_config.get('records', []):
                if record['type'] == 'CNAME':
                    # Make sure CNAME value ends with a dot if it's a FQDN
                    if '.' in record['value']:
                        if not record['value'].endswith('.'):
                            cname_value = f"{record['value']}."
                        else:
                            cname_value = record['value']
                    else:
                        cname_value = record['value']
                    zone_content += f"{record['name']}    IN    CNAME    {cname_value}\n"

            # Write zone file
            zone_file_path = f"{self.zones_dir}/db.{zone_name}"
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(zone_file_path, 'w') as f:
                    f.write(zone_content)

            # Set correct permissions and SELinux context
            commands = [
                f"chown root:named {zone_file_path}",
                f"chmod 640 {zone_file_path}",
                f"restorecon -v {zone_file_path}"
            ]
            for cmd in commands:
                self.ssh.execute_command(cmd)

            # Add zone to named.conf
            zone_conf = f"""
    zone "{zone_name}" IN {{
            type {zone_config.get('type', 'master')};
            file "db.{zone_name}";
            allow-update {{ none; }};
    }};
    """
            # Append zone configuration to named.conf
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.named_conf, 'a') as f:
                    f.write(zone_conf)

            # Verify configuration
            _, stderr = self.ssh.execute_command("named-checkconf")
            if stderr:
                raise DNSConfigError(f"Zone configuration error: {stderr}")

            # Verify zone file syntax
            _, stderr = self.ssh.execute_command(f"named-checkzone {zone_name} {zone_file_path}")
            if stderr and "OK" not in stderr:
                raise DNSConfigError(f"Zone file syntax error: {stderr}")

            # Restart named service
            self.ssh.execute_command("systemctl restart named")
            
            logger.info(f"Zone {zone_name} added successfully")

        except Exception as e:
            logger.error(f"Failed to add zone {zone_name}: {str(e)}")
            raise DNSConfigError(f"Zone configuration failed: {str(e)}")

    def add_ptr_zone(self, network: str, zone_config: Dict):
        """Add a reverse PTR zone"""
        try:
            # Calculate reverse zone name
            ip_parts = network.split('.')
            reverse_zone = f"{ip_parts[2]}.{ip_parts[1]}.{ip_parts[0]}.in-addr.arpa"

            zone_content = f"""$TTL 86400
@       IN      SOA     ns1.{reverse_zone}. admin.{reverse_zone}. (
                        {int(time.time())}  ; Serial
                        3600        ; Refresh
                        1800        ; Retry
                        604800      ; Expire
                        86400 )     ; Minimum TTL

@       IN      NS      ns1.{reverse_zone}.
@       IN      NS      ns2.{reverse_zone}.

; PTR Records
"""
            # Add PTR records
            for record in zone_config.get('records', []):
                ip = record['ip'].split('.')[-1]  # Get last octet
                zone_content += f"{ip}    IN    PTR    {record['hostname']}\n"

            # Write zone file
            zone_file_path = f"{self.zones_dir}/db.{reverse_zone}"
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(zone_file_path, 'w') as f:
                    f.write(zone_content)

            # Set correct permissions and SELinux context
            commands = [
                f"chown root:named {zone_file_path}",
                f"chmod 640 {zone_file_path}",
                f"restorecon -v {zone_file_path}"
            ]
            for cmd in commands:
                self.ssh.execute_command(cmd)

            # Add zone to named.conf
            zone_conf = f"""
zone "{reverse_zone}" IN {{
        type master;
        file "db.{reverse_zone}";
        allow-update {{ none; }};
}};
"""
            # Append zone configuration to named.conf
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.named_conf, 'a') as f:
                    f.write(zone_conf)

            # Verify configuration
            _, stderr = self.ssh.execute_command("named-checkconf")
            if stderr:
                raise DNSConfigError(f"PTR zone configuration error: {stderr}")

            # Restart named service
            self.ssh.execute_command("systemctl restart named")
            
            logger.info(f"PTR zone for {network} added successfully")

        except Exception as e:
            logger.error(f"Failed to add PTR zone for {network}: {str(e)}")
            raise DNSConfigError(f"PTR zone configuration failed: {str(e)}")

    def delete_zone(self, zone_name: str):
        """Delete a zone"""
        try:
            # Remove zone file
            zone_file = f"{self.zones_dir}/db.{zone_name}"
            self.ssh.execute_command(f"rm -f {zone_file}")

            # Read named.conf
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.named_conf, 'r') as f:
                    conf_content = f.read()

            # Remove zone configuration
            zone_pattern = f'zone "{zone_name}" IN {{[^}}]+}};'
            new_content = re.sub(zone_pattern, '', conf_content)

            # Write updated named.conf
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.named_conf, 'w') as f:
                    f.write(new_content)

            # Restart named service
            self.ssh.execute_command("systemctl restart named")
            
            logger.info(f"Zone {zone_name} deleted successfully")

        except Exception as e:
            logger.error(f"Failed to delete zone {zone_name}: {str(e)}")
            raise DNSConfigError(f"Zone deletion failed: {str(e)}")

class DnsmasqServer:
    def __init__(self, ssh_client: SSHClient):
        self.ssh = ssh_client
        self.config_path = "/etc/dnsmasq.conf"

    def install(self):
        """Install dnsmasq if not already installed"""
        stdout, _ = self.ssh.execute_command("rpm -q dnsmasq")
        if "dnsmasq-" in stdout:
            logger.info("dnsmasq is already installed")
            return

        try:
            # Install dnsmasq
            self.ssh.execute_command("yum -y install dnsmasq")
            
            # Enable and start service
            self.ssh.execute_command("systemctl enable dnsmasq")
            self.ssh.execute_command("systemctl start dnsmasq")
            
            logger.info("dnsmasq installed successfully")
            
        except Exception as e:
            raise DNSConfigError(f"Failed to install dnsmasq: {str(e)}")

    def configure(self, config: Dict):
        """Configure dnsmasq"""
        try:
            # First ensure dnsmasq is installed
            self.install()

            # Backup existing config if it exists
            self.ssh.execute_command("cp /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true")

            # Create minimal dnsmasq configuration
            conf_content = [
                f"server={config['upstream_dns']}",
                f"cache-size={config.get('cache_size', 0)}"
            ]
            
            # Write configuration
            conf_content = "\n".join(conf_content)
            with self.ssh.client.open_sftp() as sftp:
                with sftp.file(self.config_path, 'w') as f:
                    f.write(conf_content)

            logger.info("Configuration file written successfully")

            # Restart dnsmasq service
            self.ssh.execute_command("systemctl restart dnsmasq")
            
            # Verify