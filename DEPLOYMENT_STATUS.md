# Deployment Status - January 27, 2026

## Current State: DEPLOYED

### Server Details
- **Container:** LXC 700 on pve2
- **Hostname:** scheduler
- **IP Address:** 192.1.1.171
- **OS:** Ubuntu 24.04
- **Resources:** 4GB RAM, 4 cores, 40GB disk

### Services Running
- **Gunicorn:** 9 workers on 127.0.0.1:5001
- **Nginx:** Reverse proxy on port 80
- **Firewall (ufw):** Ports 22, 80 open

### Access
- **App URL:** http://192.1.1.171
- **Employee Portal:** http://192.1.1.171/employee
- **SSH:** `ssh scheduler` (alias configured on local machine)
- **SSH (root):** `ssh root@192.1.1.171`

### File Locations on Server
```
/home/scheduler/employee-scheduler/
├── app.py
├── requirements.txt
├── schedule.db          # Contains 6 schedules, 10 employees
├── .env                 # SECRET_KEY configured
├── venv/
├── static/
└── templates/
```

### Logs
- App errors: `/var/log/employee-scheduler/error.log`
- App access: `/var/log/employee-scheduler/access.log`
- Nginx: `/var/log/nginx/scheduler-*.log`

### Service Commands
```bash
sudo systemctl status employee-scheduler
sudo systemctl restart employee-scheduler
sudo journalctl -u employee-scheduler -f
```

## Next Steps
- [ ] Configure Cloudflare DNS (point domain to 192.1.1.171)
- [ ] Set Cloudflare SSL mode to "Full"
- [ ] Update Nginx config with actual domain name
- [ ] Add Cloudflare IP ranges to Nginx config (optional)
- [ ] Set up ANTHROPIC_API_KEY for Claude Code on server

## Claude Code on Server
Claude Code v2.1.20 is installed. To use:
```bash
ssh scheduler
cd employee-scheduler
export ANTHROPIC_API_KEY="your-key"
claude
```
