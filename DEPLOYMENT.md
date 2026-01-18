# Production Deployment Guide - LXC on Proxmox

Complete guide for deploying Ice Line Employee Scheduler to an LXC container on Proxmox.

## Prerequisites

- Proxmox node with LXC support
- Access to create LXC containers
- Domain name (optional, for SSL)

## Step 1: Create LXC Container

### Using Proxmox Web UI

1. **Create Container**
   - Go to your Proxmox node
   - Click "Create CT"
   - OS Template: Choose `ubuntu-22.04-standard` or `debian-12-standard`
   - VM ID: Auto-assigned (e.g., 100)
   - Hostname: `scheduler` (or your preference)
   - Password: Set root password

2. **Resource Configuration**
   - Memory: 512 MB (minimum), 1 GB recommended
   - CPU cores: 1-2 cores
   - Disk: 10 GB (plenty for app + database)
   - Network: Bridge to your network, static IP recommended

3. **Start Container**
   - Start the container after creation
   - Note the IP address assigned

### Using Command Line (SSH into Proxmox)

```bash
pct create 100 local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst \
  --hostname scheduler \
  --memory 1024 \
  --cores 2 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.100/24,gw=192.168.1.1 \
  --storage local-lvm \
  --rootfs local-lvm:10 \
  --unprivileged 0
```

## Step 2: Initial Container Setup

SSH into your LXC container:

```bash
ssh root@<container-ip>
```

### Update System

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv nginx sqlite3 git
```

### Create Application User

```bash
# Create non-root user for security
useradd -m -s /bin/bash scheduler
usermod -aG sudo scheduler

# Switch to application user
su - scheduler
```

## Step 3: Deploy Application

### Clone Repository

```bash
cd /home/scheduler
git clone <your-repo-url> employee-scheduler
cd employee-scheduler
```

Or use scp/sftp to copy files:

```bash
# From your local machine
scp -r /Users/badams/Projects/iceline/employee-scheduler/* scheduler@<container-ip>:/home/scheduler/employee-scheduler/
```

### Setup Virtual Environment

```bash
cd /home/scheduler/employee-scheduler
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Create Environment File

```bash
cat > /home/scheduler/employee-scheduler/.env << EOF
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
DATABASE_PATH=/home/scheduler/employee-scheduler/schedule.db
FLASK_DEBUG=false
EOF
chmod 600 /home/scheduler/employee-scheduler/.env
```

**⚠️ Important:** Generate a strong SECRET_KEY for production!

## Step 4: Configure Systemd Service

Create systemd service file:

```bash
sudo tee /etc/systemd/system/employee-scheduler.service > /dev/null << 'EOF'
[Unit]
Description=Ice Line Employee Scheduler
After=network.target

[Service]
Type=notify
User=scheduler
Group=scheduler
WorkingDirectory=/home/scheduler/employee-scheduler
Environment="PATH=/home/scheduler/employee-scheduler/venv/bin"
EnvironmentFile=/home/scheduler/employee-scheduler/.env
ExecStart=/home/scheduler/employee-scheduler/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:5001 \
    --timeout 120 \
    --access-logfile /var/log/employee-scheduler/access.log \
    --error-logfile /var/log/employee-scheduler/error.log \
    --log-level info \
    app:app

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

Create log directory:

```bash
sudo mkdir -p /var/log/employee-scheduler
sudo chown scheduler:scheduler /var/log/employee-scheduler
```

Enable and start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable employee-scheduler
sudo systemctl start employee-scheduler
sudo systemctl status employee-scheduler
```

## Step 5: Configure Nginx Reverse Proxy

### Install Nginx (if not already installed)

```bash
sudo apt install -y nginx
```

### Create Nginx Configuration (Cloudflare Optimized)

**Note**: Get the latest Cloudflare IP ranges from: https://www.cloudflare.com/ips/
Update the `set_real_ip_from` directives if Cloudflare adds new ranges.

```bash
sudo tee /etc/nginx/sites-available/employee-scheduler > /dev/null << 'EOF'
# Cloudflare IP ranges (update these periodically - get latest from Cloudflare)
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2c0f:f248::/32;
set_real_ip_from 2a06:98c0::/29;
real_ip_header CF-Connecting-IP;

server {
    listen 80;
    server_name scheduler.yourdomain.com;  # Change to your domain

    client_max_body_size 10M;

    # Logging
    access_log /var/log/nginx/scheduler-access.log;
    error_log /var/log/nginx/scheduler-error.log;

    # Static files
    location /static {
        alias /home/scheduler/employee-scheduler/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_set_header CF-Ray $http_cf_ray;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
    }
}
EOF
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/employee-scheduler /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Step 6: Configure Cloudflare

Since you're using Cloudflare as your proxy, SSL/TLS will be handled by Cloudflare.

**Benefits of using Cloudflare:**
- ✅ Free SSL/TLS certificates
- ✅ DDoS protection
- ✅ Web Application Firewall (WAF)
- ✅ CDN caching for static files
- ✅ Bot protection
- ✅ Analytics and insights
- ✅ Rate limiting
- ✅ Your origin server IP is hidden from attackers

### Cloudflare DNS Setup

1. **Add DNS Record in Cloudflare Dashboard**
   - Go to your Cloudflare dashboard
   - Navigate to DNS → Records
   - Add an **A** record:
     - **Name**: `scheduler` (or subdomain of your choice)
     - **IPv4**: Your LXC container's IP address
     - **Proxy status**: Orange cloud ☁️ (Proxied) - **Enable this!**
     - **TTL**: Auto

2. **SSL/TLS Settings**
   - Go to SSL/TLS → Overview
   - Set encryption mode to **"Full"** (or "Full (strict)" if you have SSL on origin)
   - This ensures end-to-end encryption

### Cloudflare Security Settings (Recommended)

1. **WAF Rules** (Optional but recommended)
   - Create custom firewall rules if needed
   - Block known bad IPs
   - Rate limiting per IP

2. **Page Rules** (Optional)
   - Cache static files: `/static/*` - Cache Everything, Edge Cache TTL: 1 month
   - Bypass cache for API: `/api/*` - Cache Level: Bypass

3. **Security Level**
   - Set to "Medium" or "High" based on your needs

### Access Control (Optional)

You can restrict access by IP if needed:
- Cloudflare Access (requires Teams plan)
- Or firewall rules in Cloudflare

### Alternative: Let's Encrypt (If not using Cloudflare proxy)

If you want SSL on the origin server itself (Cloudflare "Full (strict)" mode):

```bash
sudo apt install -y certbot python3-certbot-nginx

# Replace with your domain
sudo certbot --nginx -d scheduler.yourdomain.com

# Auto-renewal (already configured by certbot)
sudo certbot renew --dry-run
```

Then update Nginx config to listen on 443 with SSL, and set Cloudflare to "Full (strict)" mode.

## Step 7: Configure Firewall

### Basic Firewall Setup

```bash
# If using UFW
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (for Cloudflare to reach your server)
sudo ufw enable

# Note: You typically don't need to open 443 on the server
# since Cloudflare handles SSL termination
```

### Optional: Restrict HTTP Access to Cloudflare IPs Only

For extra security, you can restrict port 80 to only accept connections from Cloudflare IP ranges:

```bash
# This is optional - Cloudflare provides DDoS protection already
# Only do this if you want additional layer of security

# Download Cloudflare IP ranges and create firewall rules
# This can be complex - usually not necessary since Cloudflare protects you
```

**Recommendation**: Keep port 80 open for Cloudflare. The Cloudflare proxy already protects your origin server. Additional IP restrictions are usually unnecessary and can break if Cloudflare adds new IPs.

## Step 8: Database Backup Script

Create automated backup script:

```bash
sudo tee /home/scheduler/employee-scheduler/backup.sh > /dev/null << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/scheduler/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="/home/scheduler/employee-scheduler/schedule.db"

mkdir -p $BACKUP_DIR

# Backup database
cp $DB_FILE "$BACKUP_DIR/schedule_$DATE.db"

# Keep only last 30 days
find $BACKUP_DIR -name "schedule_*.db" -mtime +30 -delete

# Also use API backup endpoint periodically
curl -s http://localhost:5001/api/backup/export > "$BACKUP_DIR/json_backup_$DATE.json"
find $BACKUP_DIR -name "json_backup_*.json" -mtime +30 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /home/scheduler/employee-scheduler/backup.sh
```

Add to crontab (daily at 2 AM):

```bash
crontab -e
# Add this line:
0 2 * * * /home/scheduler/employee-scheduler/backup.sh >> /var/log/scheduler-backup.log 2>&1
```

## Step 9: Monitoring & Maintenance

### Check Service Status

```bash
sudo systemctl status employee-scheduler
sudo journalctl -u employee-scheduler -f  # Follow logs
```

### Check Nginx

```bash
sudo systemctl status nginx
sudo nginx -t
```

### View Logs

```bash
# Application logs
tail -f /var/log/employee-scheduler/error.log

# Nginx logs
tail -f /var/log/nginx/scheduler-error.log

# System logs
journalctl -u employee-scheduler
```

## Step 10: Update Application

When updating the application:

```bash
cd /home/scheduler/employee-scheduler
git pull  # Or copy new files
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart employee-scheduler
```

## Troubleshooting

### Service Won't Start

```bash
sudo systemctl status employee-scheduler
sudo journalctl -u employee-scheduler -n 50
```

### Check Port Binding

```bash
sudo netstat -tlnp | grep 5001
sudo ss -tlnp | grep 5001
```

### Database Permissions

```bash
sudo chown scheduler:scheduler /home/scheduler/employee-scheduler/schedule.db
sudo chmod 644 /home/scheduler/employee-scheduler/schedule.db
```

### Nginx 502 Bad Gateway

- Check if Gunicorn is running: `sudo systemctl status employee-scheduler`
- Check Gunicorn logs: `sudo tail -f /var/log/employee-scheduler/error.log`
- Verify port 5001 is listening: `sudo ss -tlnp | grep 5001`

## Performance Tuning

### Gunicorn Workers

Adjust workers based on CPU cores:
```bash
# Formula: (2 × CPU cores) + 1
# For 2 cores: 5 workers
# For 4 cores: 9 workers
```

Edit `/etc/systemd/system/employee-scheduler.service` and update `--workers` value.

### Nginx Caching (Optional)

Add to nginx config for better performance:

```nginx
location /api/schedule/ {
    proxy_cache scheduler_cache;
    proxy_cache_valid 200 5m;
    proxy_pass http://127.0.0.1:5001;
}
```

## Security Hardening

1. **Disable SSH password login** (use keys only)
2. **Set up fail2ban** for SSH protection
3. **Regular security updates**: `apt update && apt upgrade`
4. **Firewall rules** (only allow necessary ports)
5. **Change default SECRET_KEY** (already done)
6. **Run as non-root user** (already done)
7. **Set proper file permissions**

## Backup & Recovery

### Manual Backup

```bash
# Database
cp /home/scheduler/employee-scheduler/schedule.db /backup/location/

# Or use API
curl http://localhost:5001/api/backup/export -o backup.json
```

### Restore from Backup

```bash
# Stop service
sudo systemctl stop employee-scheduler

# Restore database
cp backup.db /home/scheduler/employee-scheduler/schedule.db

# Or use API import
curl -X POST -F "file=@backup.json" http://localhost:5001/api/backup/import

# Restart service
sudo systemctl start employee-scheduler
```

## Access URLs

- **Main Application**: http://your-ip or https://scheduler.yourdomain.com
- **Employee Portal**: http://your-ip/employee
- **API**: http://your-ip/api/*
