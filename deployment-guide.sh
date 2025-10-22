# deployment-guide.sh
#!/bin/bash

# ============================================
# SmartBag Production Deployment Guide
# ============================================

echo "🚀 SmartBag Deployment Script"
echo "=============================="

# 1. Update system
echo "📦 Updating system..."
sudo apt-get update
sudo apt-get upgrade -y

# 2. Install Python 3.11
echo "🐍 Installing Python 3.11..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# 3. Install MongoDB
echo "💾 Installing MongoDB..."
wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod

# 4. Install Redis
echo "⚡ Installing Redis..."
sudo apt-get install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 5. Install Nginx
echo "🌐 Installing Nginx..."
sudo apt-get install -y nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# 6. Clone repository
echo "📥 Cloning repository..."
cd /opt
sudo git clone https://github.com/yourusername/smartbag.git
cd smartbag

# 7. Create virtual environment
echo "🔧 Setting up Python environment..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 8. Configure environment
echo "⚙️  Configuring environment..."
cat > .env << EOF
ENVIRONMENT=Production
MONGO_URI=mongodb://localhost:27017
DB_NAME=smartbag_production
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=$(openssl rand -hex 32)
ALGORITHM=HS256
BCRYPT_ROUNDS=14
ALLOWED_ORIGINS=https://yourdomain.com
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENABLE_RATE_LIMITING=true
API_RATE_LIMIT_PER_MINUTE=1000
LOG_LEVEL=WARNING
EOF

# 9. Set up systemd service
echo "🔄 Creating systemd service..."
sudo cat > /etc/systemd/system/smartbag.service << EOF
[Unit]
Description=SmartBag FastAPI Application
After=network.target mongod.service redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/smartbag
Environment="PATH=/opt/smartbag/venv/bin"
ExecStart=/opt/smartbag/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 10. Configure Nginx
echo "🌐 Configuring Nginx..."
sudo cp nginx.conf /etc/nginx/nginx.conf
sudo nginx -t
sudo systemctl reload nginx

# 11. Set up SSL (Let's Encrypt)
echo "🔒 Setting up SSL..."
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com --non-interactive --agree-tos -m admin@yourdomain.com

# 12. Start application
echo "🚀 Starting application..."
sudo systemctl start smartbag
sudo systemctl enable smartbag

# 13. Verify installation
echo "✅ Verifying installation..."
sleep 5
curl http://localhost:8000/health

echo "=============================="
echo "✅ Deployment Complete!"
echo "=============================="
echo "📍 Application: http://yourdomain.com"
echo "📊 Health Check: http://yourdomain.com/health"
echo "📈 Metrics: http://yourdomain.com/api/metrics (admin only)"
echo ""
echo "Next steps:"
echo "1. Configure your DNS to point to this server"
echo "2. Test the application thoroughly"
echo "3. Set up monitoring and alerting"
echo "4. Configure automated backups"
echo ""
echo "Useful commands:"
echo "  - Check logs: sudo journalctl -u smartbag -f"
echo "  - Restart app: sudo systemctl restart smartbag"
echo "  - Check status: sudo systemctl status smartbag"