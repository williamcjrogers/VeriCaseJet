# VeriCase Deployment Status

**Last Updated**: 2025-12-05 06:35 UTC

## 🚀 Latest Deployment

### Current Version
- **Commit**: `8bba4354` - "Fix infinite loop in evidence page data loading"
- **GitHub**: ✅ Pushed to main branch
- **Docker Hub**: ✅ Published
- **Local Environment**: ✅ Running

### What's New in This Version
- ✅ **Bug Fix**: Fixed infinite loop in evidence page causing excessive API requests
- ✅ **Performance**: Improved evidence page loading by preventing duplicate data loads
- ✅ **UI Version**: Updated to 2.0.5 with cache busting
- ✅ **Project Management**: Can delete and rename projects from UI (previous version)
- ✅ **Case Management**: Can delete cases from UI (previous version)

## 📦 Docker Images - Docker Hub

**Repository**: wcjrogers/vericase-api

- ✅ `latest` - Live (11GB) - Points to `8bba4354`
- ✅ `8bba4354` - Current version with infinite loop fix
- ✅ `66d2d5b7` - Previous version (project delete/edit)

**Pull**: `docker pull wcjrogers/vericase-api:latest`

## 🔄 Deployment Status

| Component | GitHub | Docker Hub | Local | EKS |
|-----------|--------|------------|-------|-----|
| API Code | ✅ 8bba4354 | ✅ 8bba4354 | ✅ Running | 🔄 Auto-deploy |
| UI Files | ✅ 2.0.5 | ✅ 2.0.5 | ✅ Running | 🔄 Auto-deploy |
