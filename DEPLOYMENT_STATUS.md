# VeriCase Deployment Status

**Last Updated**: 2025-12-05 06:24 UTC

## 🚀 Latest Deployment

### Current Version
- **Commit**: `66d2d5b7` - "Add PUT and DELETE endpoints for projects and cases"
- **GitHub**: ✅ Pushed to main branch
- **Docker Hub**: ✅ Published
- **Local Environment**: ✅ Running

### What's New in This Version
- ✅ **Project Management**: Can now delete and rename projects from UI
- ✅ **Case Management**: Can now delete cases from UI
- ✅ **API Endpoints**: Added PUT `/api/projects/{id}` and DELETE `/api/projects/{id}`, DELETE `/api/cases/{id}`

## 📦 Docker Images - Docker Hub

**Repository**: wcjrogers/vericase-api

- ✅ `latest` - Live (11GB)
- ✅ `66d2d5b7` - Current version
- ✅ `20251205-062004` - Timestamped

**Pull**: `docker pull wcjrogers/vericase-api:latest`

## 🔄 Deployment Status

| Component | GitHub | Docker Hub | Local | EKS |
|-----------|--------|------------|-------|-----|
| API Code | ✅ 66d2d5b7 | ✅ 66d2d5b7 | ✅ Running | 🔄 Auto-deploy |
| UI Files | ✅ Latest | ✅ Latest | ✅ Running | 🔄 Auto-deploy |
