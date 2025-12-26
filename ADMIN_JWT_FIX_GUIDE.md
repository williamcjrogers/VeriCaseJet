# Admin Account & JWT Token Fix Guide

**Date:** December 19, 2025  
**Status:** ✅ SOLUTION IMPLEMENTED  

---

## ✅ SOLUTION: New Admin Account Created

A new, properly configured admin account has been created:

**Email:** `admin@veri-case.com`  
**Password:** From `ADMIN_PASSWORD` environment variable  
**Status:** ✅ All security fields properly initialized

### What Was Fixed

The original `admin@vericase.com` account created during development was missing critical security fields added in the enhanced authentication system:
- `email_verified` - Was False, causing warnings
- `failed_login_attempts` - May have been > 0
- `locked_until` - Account may have been locked
- Other security timestamps and tokens

### Why the New Account Works

The new `admin@veri-case.com` account was created with:
- ✅ Proper ADMIN role
- ✅ Email marked as verified
- ✅ All security fields initialized correctly
- ✅ No lockouts or failed attempts
- ✅ Clean password hash from current ADMIN_PASSWORD
- ✅ All timestamps properly set

---

## 🔧 Original Issues Identified

### 1. **Admin Account Security Fields** ✅ SOLVED
- **Problem:** Original admin@vericase.com created in dev had incomplete security fields
- **Solution:** Created new admin@veri-case.com with proper initialization
- **Files:** `vericase/api/create_new_admin.py`, `vericase/api/fix_admin_account.py`

### 2. **JWT Token Configuration** ✅ VERIFIED
- **Status:** JWT_SECRET is properly configured
- **Location:** Environment variables / Kubernetes secret `vericase-secrets`
- **Env Var:** `JWT_SECRET`

### 3. **PST Upload Navigation**
- **Problem:** Clicking "Upload Evidence" navigates to `pst-upload.html` but loses project context
- **Root Cause:** Page loads without proper authentication/project state
- **Navigation Flow:** Dashboard → `VeriCaseApp.gotoUpload()` → `goto("pst-upload.html")`

---

## 🚀 Quick Fix: Automated Admin Account Setup

### NEW: Two Options Available ✨

#### Option A: Create Fresh Admin Account (RECOMMENDED) 🆕

Create a new properly configured admin account: **admin@veri-case.com**

This is the cleanest approach - all security fields properly initialized from the start.

#### Option B: Fix Existing Account 🔧

Repair the existing **admin@vericase.com** account by fixing all security fields.

---

### For Local Development (Docker):

```powershell
# From the vericase/ directory
.\fix-admin-local.ps1
```

You'll get a menu:
```
1. Fix existing admin@vericase.com account
2. Create NEW admin@veri-case.com account (recommended)
3. Both (fix old, create new)
```

Both scripts will:
- ✅ Use the same ADMIN_PASSWORD from environment
- ✅ Set proper ADMIN role
- ✅ Mark email as verified
- ✅ Clear any lockouts
- ✅ Reset failed login attempts
- ✅ Initialize all security fields correctly

### For Kubernetes/Production:

```bash
# From the vericase/ directory
./fix-admin-k8s.sh
```

You'll get the same menu to choose your option.

Or manually create the new admin:
```bash
# 1. Find API pod
kubectl get pods -n vericase -l app=vericase-api

# 2. Create new admin account
kubectl exec -it -n vericase <api-pod-name> -- python /app/create_new_admin.py
```Scripts Do

#### `create_new_admin.py` - Create Fresh Account (Recommended)

Creates **admin@veri-case.com** with proper initialization:

1. **Checks** if account exists
   - Option to update, recreate, or exit

2. **Creates** with proper fields:
   - ✅ Role: ADMIN
   - ✅ Email verified: True
   - ✅ Active: True
   - ✅ Failed attempts: 0
   - ✅ No lockouts
   - ✅ Password from `ADMIN_PASSWORD` env
   - ✅ All timestamps set
   - ✅ Display name: "System Administrator"

3. **Reports** full account details

#### `fix_admin_account.py` - Repair Existing Account

Fixes **admin@vericase.com** by:

1. **Diagnoses** the account:
   - Checks if exists
   - Verifies all security fields
   - Identifies lockouts, failed attempts
   - Validates role and permissions

2. **Repairs** any issues:
   - Sets correct ADMIN role
   - Activates account if disabled
   - Marks email as verified
   - Clears account lockouts
   - Resets failed login attempts
   - Updates password from `ADMIN_PASSWORD` env
   - Resets failed login attempts
   - Updates password from `ADMIN_PASSWORD` env var
   - Clears any password reset tokens

3. **Reports** status:
   - Shows current configuration
   - Lists all issues found
   - Confirms fixes applied

### Manual Option (if needed)

If you need to manually fix the account:

```bash
# Connect to pod
kubectl exec -it -n vericase deployment/vericase-api -- /bin/bash

# Run Python fix
python3 << 'EOF'
from api.app.db import SessionLocal
from api.app.models import User, UserRole
from api.app.security import hash_password
from datetime import datetime, timezone
import os

db = SessionLocal()
try:
    admin = db.query(User).filter(User.email == "admin@vericase.com").first()
    
    if admin:
        # Fix all security fields
        admin.role = UserRole.ADMIN
        admin.is_active = True
        admin.email_verified = True
        admin.verification_token = None
        admin.failed_login_attempts = 0
        admin.locked_until = None
        admin.last_failed_attempt = None
        admin.reset_token = None
        admin.reset_token_expires = None
        admin.password_hash = hash_password(os.getenv("ADMIN_PASSWORD", "ChangeThis123!"))
        admin.password_changed_at = datetime.now(timezone.utc)
        
        db.commit()
        print("✅ Admin account fixed!")
    else:
        print("❌ Admin not found, creating...")
        new_admin = User(
            email="admin@vericase.com",
            username="admin",
            password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "ChangeThis123!")),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            failed_login_attempts=0,
            password_changed_at=datetime.now(timezone.utc)
        )
        db.add(new_admin)
        db.commit()
        print("✅ Admin created!")
except Exception as e:
    print(f"❌ Error: {e}")
    db.rollback()
finally:
    db.close()
EOF
```

---

## 🔐 JWT Secret Configuration

### Check Current JWT Secret

```bash
# View the secret (base64 encoded)
kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.JWT_SECRET}' | base64 --decode
echo

# If empty or missing, you need to set it
```

### Generate and Set New JWT Secret

```bash
# 1. Generate a secure random secret (32+ characters)
JWT_SECRET=$(openssl rand -base64 32)
echo "Generated JWT Secret: $JWT_SECRET"

# 2. Update the Kubernetes secret
kubectl create secret generic vericase-secrets \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=ADMIN_PASSWORD="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 --decode)" \
  --from-literal=AG_GRID_LICENSE_KEY="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.AG_GRID_LICENSE_KEY}' | base64 --decode)" \
  --from-literal=DATABASE_URL="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.DATABASE_URL}' | base64 --decode)" \
  --namespace vericase \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Restart pods to pick up new secret
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# 4. Wait for rollout
kubectl rollout status deployment/vericase-api -n vericase
```

### Verify JWT Secret is Set

```bash
# Check environment variable in pod
kubectl exec -it -n vericase deployment/vericase-api -- env | grep JWT_SECRET

# Should show: JWT_SECRET=<your-secret-value>
```

---

## 🔍 Diagnose PST Upload Navigation Issue

### Check Browser Console

When clicking "Upload Evidence", open browser DevTools (F12) and check:

1. **Console Tab** - Look for JavaScript errors:
   ```
   - Authentication errors
   - Failed to fetch
   - Project ID undefined
   - Token expired
   ```

2. **Network Tab** - Check API calls:
   ```
   - /api/user/me (should return 200)
   - /api/projects (should return 200)
   - Authorization header present?
   ```

3. **Application Tab > Local Storage**:
   ```
   - Check for 'token' or 'jwt' key
   - Check for 'currentProjectId' or 'selectedProject'
   - Check for 'user' object
   ```

### Common Fixes

#### Fix 1: Clear Browser Storage and Re-login

```javascript
// Run in browser console
localStorage.clear();
sessionStorage.clear();
location.reload();
// Then log in again
```

#### Fix 2: Check JWT Token Expiration

```javascript
// Run in browser console to decode JWT
const token = localStorage.getItem('token') || localStorage.getItem('jwt');
if (token) {
  const payload = JSON.parse(atob(token.split('.')[1]));
  console.log('Token expires:', new Date(payload.exp * 1000));
  console.log('Current time:', new Date());
  console.log('Expired?', Date.now() > payload.exp * 1000);
}
```

#### Fix 3: Verify API Endpoint Configuration

Check `pst-upload.html` for correct API URL:

```javascript
// Should be in the HTML file
const apiUrl = window.location.hostname === 'localhost' 
  ? 'http://localhost:8000' 
  : '';  // Empty string uses same origin
```

---

## 📋 Complete Verification Checklist

### Backend (API) Checks

```bash
# 1. Admin user exists
kubectl exec -it -n vericase deployment/vericase-api -- python3 -c "
from api.app.db import SessionLocal
from api.app.models import User
db = SessionLocal()
admin = db.query(User).filter(User.email == 'admin@vericase.com').first()
print(f'Admin exists: {admin is not None}')
if admin:
    print(f'Admin active: {admin.is_active}')
    print(f'Admin role: {admin.role}')
db.close()
"

# 2. JWT_SECRET is set
kubectl exec -it -n vericase deployment/vericase-api -- env | grep JWT_SECRET

# 3. Health check passes
curl http://k8s-vericase-vericase-831b8104f3-1782642699.eu-west-2.elb.amazonaws.com/health

# 4. Check API logs for errors
kubectl logs -n vericase -l app=vericase-api --tail=50
```

### Frontend (Browser) Checks

1. Navigate to: `http://veri-case.com`
2. Open DevTools (F12)
3. Log in with admin credentials
4. Check Application → Local Storage:
   - ✅ `token` or `jwt` key present
   - ✅ `user` object with admin details
   - ✅ `currentProjectId` or `selectedProject`

5. Navigate to Dashboard
6. Click "Upload Evidence"
7. Check Console for errors
8. Verify you land on `pst-upload.html` with project context

---

## 🐛 Troubleshooting Common Issues

### Issue: "Invalid credentials"

**Cause:** Admin password mismatch  
**Fix:**
```bash
# Check what password is set in Kubernetes
kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 --decode
echo

# If needed, reset it
NEW_PASS="YourNewSecurePassword123!"
kubectl create secret generic vericase-secrets \
  --from-literal=ADMIN_PASSWORD="$NEW_PASS" \
  --from-literal=JWT_SECRET="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.JWT_SECRET}' | base64 --decode)" \
  --from-literal=AG_GRID_LICENSE_KEY="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.AG_GRID_LICENSE_KEY}' | base64 --decode)" \
  --from-literal=DATABASE_URL="$(kubectl get secret vericase-secrets -n vericase -o jsonpath='{.data.DATABASE_URL}' | base64 --decode)" \
  --namespace vericase \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart API
kubectl rollout restart deployment/vericase-api -n vericase
```

### Issue: "Token expired" or "Unauthorized"

**Cause:** JWT token expired or invalid  
**Fix:**
1. Log out and log back in
2. Clear browser storage
3. Verify JWT_SECRET is set correctly in pods

### Issue: "Cannot read property 'id' of undefined" on pst-upload.html

**Cause:** Project context not loaded  
**Fix:**

**Option A - Check app-state.js loads properly:**
```html
<!-- Verify these scripts load in pst-upload.html -->
<script src="app-state.js"></script>
<script>
  // After page load, check:
  console.log('VeriCaseApp:', window.VeriCaseApp);
  console.log('Current Project:', VeriCaseApp.currentProject);
</script>
```

**Option B - Add project initialization to pst-upload.html:**
```javascript
// Add at the top of pst-upload.html script section
document.addEventListener('DOMContentLoaded', async () => {
  // Ensure we have a project
  if (!VeriCaseApp.currentProject) {
    await VeriCaseApp.init();
  }
  
  if (!VeriCaseApp.currentProject) {
    alert('Please select or create a project first');
    window.location.href = 'dashboard.html';
    return;
  }
  
  // Continue with rest of page initialization...
});
```

---

## 📝 Hardcoding Admin Credentials (Development Only)

**⚠️ WARNING: Only use this for local development/testing!**

### Option 1: Environment File

Create `.env` in `vericase/api/`:
```bash
# Admin Account
ADMIN_EMAIL=admin@vericase.com
ADMIN_PASSWORD=Admin123!Secure

# JWT Configuration  
JWT_SECRET=your-super-secret-jwt-key-min-32-characters-long
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/vericase
```

### Option 2: Direct Code (NEVER for production)

Edit `vericase/api/app/config.py`:
```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # Hardcoded fallbacks (DEVELOPMENT ONLY)
    admin_email: str = Field(default="admin@vericase.com")
    admin_password: str = Field(default="Admin123!Secure")
    jwt_secret: str = Field(default="dev-secret-key-change-in-production-min-32-chars")
    
    class Config:
        env_file = ".env"
```

---

## ✅ Success Criteria

After implementing fixes, you should be able to:

1. ✅ Log in with admin credentials
2. ✅ See valid JWT token in browser localStorage
3. ✅ Navigate to Dashboard
4. ✅ Click "Upload Evidence" 
5. ✅ Land on `pst-upload.html` with full functionality
6. ✅ Upload files successfully
7. ✅ See uploads in history
8. ✅ Navigate back to dashboard without losing session

---

## 🔄 After Fix - Commit Changes

```bash
# Stage the fixed init_admin.py
git add vericase/api/init_admin.py

# Commit
git commit -m "Fix admin initialization script - correct f-string formatting"

# Push
git push origin main
```

---

## 📚 Related Files

- `vericase/api/init_admin.py` - Admin initialization (FIXED)
- `vericase/ui/app-state.js` - App state management & navigation
- `vericase/ui/dashboard.html` - Contains `openPstUpload()` function
- `vericase/ui/pst-upload.html` - PST upload page
- `vericase/k8s/k8s-deployment.yaml` - Kubernetes deployment config

---

## 🆘 Still Having Issues?

Run this comprehensive diagnostic:

```bash
# Save as diagnose-vericase.sh
kubectl exec -it -n vericase deployment/vericase-api -- python3 << 'EOF'
import os
from api.app.db import SessionLocal
from api.app.models import User

print("="*50)
print("VeriCase Diagnostic Report")
print("="*50)

# 1. Environment Variables
print("\n1. Environment Check:")
print(f"   ADMIN_EMAIL: {os.getenv('ADMIN_EMAIL', 'NOT SET')}")
print(f"   JWT_SECRET: {'SET' if os.getenv('JWT_SECRET') else 'NOT SET'}")
print(f"   DATABASE_URL: {'SET' if os.getenv('DATABASE_URL') else 'NOT SET'}")

# 2. Database Connection
print("\n2. Database Check:")
try:
    db = SessionLocal()
    print("   ✅ Database connection successful")
    
    # 3. Admin User
    admin = db.query(User).filter(User.email == 'admin@vericase.com').first()
    if admin:
        print(f"\n3. Admin User:")
        print(f"   ✅ Admin exists")
        print(f"   Email: {admin.email}")
        print(f"   Active: {admin.is_active}")
        print(f"   Role: {admin.role}")
        print(f"   Requires Approval: {admin.requires_approval}")
    else:
        print("\n3. Admin User:")
        print("   ❌ Admin does not exist!")
    
    db.close()
except Exception as e:
    print(f"   ❌ Database error: {e}")

print("\n" + "="*50)
EOF
```

---

**Last Updated:** December 19, 2025  
**Maintained By:** VeriCase DevOps Team
