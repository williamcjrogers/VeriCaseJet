# VeriCase - Ultra-Fast Local Setup

## 🚀 Fastest Way (2 Minutes) - Use Docker Hub

Pull your latest deployed images and run them locally:

```powershell
cd "c:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"

# Pull latest images from Docker Hub
.\scripts\dev.ps1 pull

# Start everything
.\scripts\dev.ps1 start -Hub

# Open dashboard
start http://localhost:8010/ui/dashboard.html
```

**Done!** You're now running the exact same code that's deployed on EKS, but locally.

---

## ⚡ Two Workflows

### Workflow 1: Test Latest Deployed Version (FASTEST)

**Use when:** You want to test the latest deployed version locally

```powershell
# Pull latest from Docker Hub
.\scripts\dev.ps1 pull

# Start with pre-built images
.\scripts\dev.ps1 start -Hub
```

**Speed:** ~2 minutes
**Updates:** Only when you pull new images
**Best for:** Testing production-like environment locally

---

### Workflow 2: Local Development with Hot Reload

**Use when:** You're making code changes and want instant feedback

```powershell
# Build and start with hot reload
.\scripts\dev.ps1 start

# Edit code in api/app/ or ui/
# Save file → Refresh browser → See changes!
```

**Speed:** ~5 minutes first time, then instant hot reload
**Updates:** Automatic when you save files
**Best for:** Active development

---

## 📋 Common Commands

```powershell
# View logs
.\scripts\dev.ps1 logs api

# Check health
.\scripts\dev.ps1 health

# Restart a service
.\scripts\dev.ps1 restart worker

# Stop everything
.\scripts\dev.ps1 stop

# See all commands
.\scripts\dev.ps1 help
```

---

## 🎯 Your New Development Cycle

### Before (SLOW - 10+ minutes)
1. Edit code locally
2. Push to GitHub
3. Wait for CI/CD to build Docker image
4. Wait for deployment to EKS
5. Test on EKS
6. Find bugs
7. Repeat...

### After Option 1: Docker Hub (FAST - 2 minutes)
1. Push code to GitHub (deploy to EKS as usual)
2. Pull latest image: `.\scripts\dev.ps1 pull`
3. Run locally: `.\scripts\dev.ps1 start -Hub`
4. Test locally first
5. If it works locally, it'll work on EKS!

### After Option 2: Hot Reload (INSTANT - 1 second)
1. Start once: `.\scripts\dev.ps1 start`
2. Edit code → Save → Refresh → Test (1 second!)
3. Iterate locally until perfect
4. Push to GitHub only when ready
5. No more waiting for CI/CD!

---

## 🔍 Which Workflow Should I Use?

| Scenario | Use | Command |
|----------|-----|---------|
| Just pushed to GitHub, want to test locally | Docker Hub | `.\scripts\dev.ps1 start -Hub` |
| Making code changes, need fast iteration | Hot Reload | `.\scripts\dev.ps1 start` |
| Testing production behavior | Docker Hub | `.\scripts\dev.ps1 start -Hub` |
| Debugging/developing new features | Hot Reload | `.\scripts\dev.ps1 start` |
| Want the exact deployed version | Docker Hub | `.\scripts\dev.ps1 start -Hub` |

---

## 🎉 Time Saved

**Before:**
- Every test cycle: 10+ minutes (push → CI/CD → deploy → test)
- 10 iterations: 100+ minutes (1.7 hours)

**After (Docker Hub):**
- First pull: 2 minutes
- Every test: Instant (already running)
- 10 iterations: 2 minutes total

**After (Hot Reload):**
- First start: 5 minutes
- Every change: 1 second
- 10 iterations: 5 minutes total

**You just saved hours of waiting time!** 🎉

---

## 🆘 Troubleshooting

### Docker Hub images not pulling
```powershell
# Check Docker Hub status
docker pull wcjrogers/vericase-api:latest

# Check your Docker Hub credentials
docker login
```

### Services won't start
```powershell
# Check what's running
.\scripts\dev.ps1 status

# View logs
.\scripts\dev.ps1 logs api

# Reset everything
docker-compose down -v
.\scripts\dev.ps1 start -Hub
```

### Hot reload not working
```powershell
# Make sure you're not using -Hub flag
.\scripts\dev.ps1 stop
.\scripts\dev.ps1 start  # Without -Hub

# Check logs
.\scripts\dev.ps1 logs api
```

---

## 📚 More Info

- Full guide: [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)
- Main README: [README.md](README.md)
- Docker compose files:
  - `docker-compose.yml` - Local build with hot reload
  - `docker-compose.hub.yml` - Pre-built images from Docker Hub

---

## ✅ Next Steps

1. **Try Docker Hub mode** (fastest):
   ```powershell
   .\scripts\dev.ps1 pull
   .\scripts\dev.ps1 start -Hub
   ```

2. **Or try hot reload** (best for development):
   ```powershell
   .\scripts\dev.ps1 start
   # Edit a file and see it reload!
   ```

3. **Never wait for CI/CD again** during development! 🚀
