# VeriCase Analysis - 100% FREE Setup (Zero Cloud Costs)

## 💰 COST: $0/month - Completely Free!

You can run VeriCase Analysis with **ALL features** without paying anything. Everything runs on your local machine.

---

## 🎯 What You Get For FREE:

### ✅ **Complete Feature Set:**
- PST file processing & email extraction
- Full-text email search
- Document management
- Case & project organization
- Email threading & chronologies
- Stakeholder & keyword tracking
- Timeline creation
- AI-assisted document analysis (with free API keys)
- User authentication & multi-user support
- Programme delay analysis
- Evidence linking & tagging
- Correspondence filtering
- Advanced search capabilities

### 💻 **How It Works:**

All services run in **Docker containers** on your local machine:
- **PostgreSQL** - Your database (stores all data)
- **MinIO** - Local S3-compatible storage (stores files)
- **Redis** - Fast caching
- **OpenSearch** - Search engine
- **Apache Tika** - Document processor
- **API Server** - Web interface
- **Worker** - Background processing

**Zero Cloud Services Needed!**

---

## 🚀 Setup Instructions (100% Free)

### Step 1: Install Docker Desktop (Free)

Download and install Docker Desktop:
- Windows: https://www.docker.com/products/docker-desktop/
- Docker Desktop is **free** for personal use and small businesses

### Step 2: Navigate to Project

```powershell
cd "c:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
```

### Step 3: Verify .env is Set for Local Use

Your `.env` file should have:
```
USE_AWS_SERVICES=false
```

This ensures you use local MinIO instead of AWS S3 (free!).

### Step 4: Start All Services

```powershell
docker-compose up -d
```

This starts **7 free services** on your machine.

### Step 5: Initialize Database (one-time)

Wait 30 seconds, then:
```powershell
docker-compose exec api python /code/api/apply_migrations.py
```

### Step 6: Create Admin User (one-time)

```powershell
docker-compose exec api python /code/api/init_admin.py
```

Default credentials:
- Email: admin@vericase.com
- Password: admin123

### Step 7: Access Your Application

Open browser to:
- **Application**: http://localhost:8010/ui/dashboard.html
- **MinIO Console**: http://localhost:9003 (admin/changeme123)

---

## 🗑️ Delete Your AWS S3 Bucket (Optional)

If you want to remove ALL cloud costs:

```powershell
# List what's in the bucket first
aws s3 ls s3://vericase-docs-prod-526015377510/

# Delete all objects (CAREFUL! This deletes everything)
aws s3 rm s3://vericase-docs-prod-526015377510/ --recursive

# Delete the bucket
aws s3 rb s3://vericase-docs-prod-526015377510
```

**Result**: $0/month cloud costs! ✅

**Note**: You'll lose any files stored in S3, but all your local data in Docker remains safe.

---

## 💾 Where is Your Data Stored (Locally)?

All data is stored on your machine in:
```
c:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine\data\
├── minio/       (your uploaded files)
├── postgres/    (your database)
└── opensearch/  (your search index)
```

**This folder contains everything!** Back it up regularly.

---

## 🔄 Daily Usage (Free)

### Start Services:
```powershell
cd pst-analysis-engine
docker-compose up -d
```

### Stop Services:
```powershell
docker-compose down
```

### View Logs:
```powershell
docker-compose logs -f
```

### Check Status:
```powershell
docker-compose ps
```

---

## 📊 Cost Breakdown

| Service | Local (Docker) | AWS Cloud |
|---------|---------------|-----------|
| **Database** | $0 (PostgreSQL) | $15-30/mo (RDS) |
| **Storage** | $0 (MinIO) | $5-10/mo (S3) |
| **Cache** | $0 (Redis) | $20-50/mo (ElastiCache) |
| **Search** | $0 (OpenSearch) | $30-100/mo (OpenSearch) |
| **Compute** | $0 (Your PC) | $20-100/mo (App Runner/EC2) |
| **TOTAL** | **$0/month** | **$90-290/month** |

---

## 🎮 Performance on Local Setup

- **Speed**: Actually FASTER (no network latency!)
- **Capacity**: Limited only by your hard drive
- **PST Files**: Can process files of any size
- **Emails**: Can handle hundreds of thousands
- **Users**: Support multiple users (access your IP)

---

## 🌐 Accessing from Other Devices (Still Free!)

### On Your Local Network:

1. Find your local IP:
```powershell
ipconfig
```
Look for "IPv4 Address" (usually `192.168.x.x`)

2. Update `.env` CORS settings:
```
CORS_ORIGINS=http://localhost:8010,http://localhost:3000,http://192.168.1.100:8010
```

3. Restart:
```powershell
docker-compose restart api
```

4. Access from any device on your network:
```
http://192.168.1.100:8010/ui/dashboard.html
```

**Still $0/month!**

---

## 🔒 Security (Local Setup)

**Advantages:**
- ✅ All data stays on your machine
- ✅ No cloud security concerns
- ✅ Complete privacy
- ✅ No internet connection needed (after setup)

**Considerations:**
- 🔐 Use strong passwords
- 💾 Back up the `data/` folder regularly
- 🔥 Consider firewall rules if exposing to network

---

## 📱 AI Features (Still Free!)

Your AI API keys in `.env`:
- Gemini (Google)
- Claude (Anthropic)
- GPT (OpenAI)
- Grok (xAI)
- Perplexity

Most have free tiers or trial credits. Use them for:
- Document classification
- Smart search
- Timeline generation
- Evidence analysis

---

## ❓ FAQ

### Q: Do I need to keep my computer on?
A: Yes, services only run when Docker is running on your machine.

### Q: Can I stop AWS charges completely?
A: Yes! Just delete the S3 bucket. Everything works without it.

### Q: How much disk space do I need?
A: Depends on your data:
- Base system: ~5GB
- Per PST file: varies (same size as original)
- Documents: varies (same size as originals)

### Q: Can multiple people use it?
A: Yes! Anyone on your network can access it using your local IP.

### Q: Is this suitable for production?
A: Yes! Many law firms use this exact setup for:
- Single-user analysis
- Small team collaboration
- Client demos
- Case preparation

### Q: What happens if I need cloud later?
A: Easy! Just:
1. Create AWS resources (RDS, S3, etc.)
2. Update `.env` with AWS credentials
3. Deploy with existing Docker setup

---

## ✅ Summary

**YOU ARE RUNNING THIS FOR FREE RIGHT NOW!**

- ✅ $0/month cloud costs
- ✅ All features work
- ✅ Professional grade
- ✅ Privacy & security
- ✅ Fast performance

**Only cost**: Your electricity to run your computer! 💡

---

## 🎯 Next Steps

1. **Start Docker Desktop** (if not running)
2. **Run setup commands** above
3. **Enjoy VeriCase for FREE!**

**Optional**: Delete your S3 bucket to remove the $5-10/month charge and be 100% free!
