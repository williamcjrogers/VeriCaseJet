# VeriCase Website Integration Guide

## Overview
The VeriCase marketing website (veri-case.com) is now fully integrated with the VeriCase application, directing users through the proper registration and approval workflow.

## User Flow

### From Website to Application

1. **User visits veri-case.com**
2. **Clicks "Get Started" or "Login"**
   - "Get Started" → Redirects to `signup.html`
   - "Login" → Redirects to `login.html`
3. **New User Registration Flow**:
   - Fill out signup form
   - Account created but **inactive**
   - Admin receives notification
   - User waits for approval
4. **Admin Approval**:
   - Admin logs in to app
   - Reviews pending users in approval panel
   - Approves or rejects
   - User receives email notification
5. **User Login**:
   - User receives approval email
   - Logs in at `login.html`
   - Redirected to dashboard
   - Can now use full platform

## Website Changes Made

### File: `frontend/src/pages/Login.jsx`

**Before**: Website had its own authentication  
**After**: Redirects to VeriCase app for authentication

**Changes**:
```javascript
// Login button → app.veri-case.com/ui/login.html
// Get Started button → app.veri-case.com/ui/signup.html
```

### File: `frontend/src/components/sections/Navigation.jsx`

**Changes**:
- "Login" button → Redirects to app login page
- "Get Started" button → Redirects to app signup page
- "Open App" button (when logged in) → Redirects to dashboard

## Environment Configuration

### Development
```bash
REACT_APP_APP_URL=http://localhost:8010/ui/
```

### Production
```bash
REACT_APP_APP_URL=https://app.veri-case.com/ui/
```

## URL Structure

### Marketing Website (veri-case.com)
- Homepage: `https://www.veri-case.com/`
- About: `https://www.veri-case.com/#about`
- Pricing: `https://www.veri-case.com/#pricing`
- Platform: `https://www.veri-case.com/#platform`

### Application (app.veri-case.com)
- Signup: `https://app.veri-case.com/ui/signup.html`
- Login: `https://app.veri-case.com/ui/login.html`
- Dashboard: `https://app.veri-case.com/ui/dashboard.html`
- Admin Approvals: `https://app.veri-case.com/ui/admin-approvals.html`

## Registration & Approval Workflow

### 1. User Registration
**Page**: `signup.html`

**Form Fields**:
- First Name & Last Name
- Work Email
- Company/Organization
- Role (Solicitor, Barrister, Expert, etc.)
- Password (min 8 chars, strength indicator)
- Reason for Access (optional)

**Process**:
```
User submits form
  ↓
POST /api/auth/register (requires_approval: true)
  ↓
User account created (is_active: false)
  ↓
Email sent to user: "Pending approval"
  ↓
Email sent to all admins: "New user awaiting approval"
```

### 2. Admin Approval
**Page**: `admin-approvals.html`

**Admin Actions**:
- View all pending registrations
- See user details (name, company, role, reason)
- Approve with role assignment (Admin/Editor/Viewer)
- Reject with optional reason

**Process**:
```
Admin clicks "Approve"
  ↓
POST /api/admin/users/approve
  ↓
User account activated (is_active: true)
  ↓
Email sent to user: "Account approved! You can now login"
```

### 3. User Login
**Page**: `login.html`

**Process**:
```
User enters credentials
  ↓
POST /api/auth/login
  ↓
If account not active → Error: "Account pending approval"
  ↓
If approved → Token issued
  ↓
Redirect to dashboard
```

## API Endpoints

### Authentication
- `POST /api/auth/register` - User registration (with approval flag)
- `POST /api/auth/login` - User login (checks is_active)

### Admin Approval
- `GET /api/admin/users/pending` - List pending users (admin only)
- `POST /api/admin/users/approve` - Approve/reject user (admin only)
- `GET /api/admin/users/all` - List all users (admin only)

## Email Notifications

### User Emails
1. **Registration Confirmation**
   - Subject: "Welcome to VeriCase - Pending Approval"
   - Content: "Your account is being reviewed by an administrator"

2. **Approval Notification**
   - Subject: "VeriCase Account Approved"
   - Content: "Your account has been approved! You can now login"
   - Includes login link

3. **Rejection Notification**
   - Subject: "VeriCase Registration Update"
   - Content: Reason for rejection (if provided)

### Admin Emails
1. **New Registration Alert**
   - Subject: "New VeriCase Registration - Approval Required"
   - Content: User details (name, company, email, reason)
   - Includes link to approval panel

## Security Features

### Registration Security
- ✅ Password strength validation (min 8 chars)
- ✅ Email uniqueness check
- ✅ Accounts inactive by default
- ✅ Admin approval required
- ✅ Audit trail in user meta

### Admin Security
- ✅ Admin role required for approval endpoints
- ✅ 403 Forbidden if non-admin tries to access
- ✅ All actions logged
- ✅ Email notifications for transparency

## Testing the Integration

### Local Development

1. **Start VeriCase App**:
   ```bash
   docker compose up -d
   ```

2. **Start Website** (in website directory):
   ```bash
   cd frontend
   npm start
   ```

3. **Test Flow**:
   - Visit `http://localhost:3000` (website)
   - Click "Get Started"
   - Should redirect to `http://localhost:8010/ui/signup.html`
   - Fill out form
   - Login as admin at `http://localhost:8010/ui/login.html`
   - Go to admin approvals
   - Approve the new user
   - New user can now login

### Production Deployment

**Website** (veri-case.com):
```bash
# Set environment variable
export REACT_APP_APP_URL=https://app.veri-case.com/ui/

# Build
npm run build

# Deploy to hosting (Vercel/Netlify/etc)
```

**Application** (app.veri-case.com):
```bash
# Already running on Docker
docker compose up -d
```

## Cross-Domain Considerations

### Token Handling
- Website redirects to app with URL
- App handles authentication
- Token stored in app's localStorage
- No cross-domain token sharing needed

### CORS Configuration
If website needs to call app API directly:
```python
# api/app/config.py
CORS_ORIGINS=https://www.veri-case.com,https://app.veri-case.com
```

## Admin Setup

### Initial Admin Account
```
Email: admin@test.com
Password: password12345
```

**Important**: Change this password in production!

### Creating Additional Admins
1. Login as admin
2. Go to admin approvals
3. Approve new user
4. Manually update role to ADMIN in database:
   ```sql
   UPDATE users SET role = 'ADMIN' WHERE email = 'newadmin@company.com';
   ```

## Monitoring

### Check Pending Approvals
- Dashboard shows "Approvals" button with badge count
- Direct URL: `/ui/admin-approvals.html`
- API: `GET /api/admin/users/pending`

### User Activity
- Last login tracked in `users.last_login_at`
- Signup date in `users.meta.signup_date`
- Approval status in `users.meta.approval_status`

## Troubleshooting

### "Account pending approval" error
- User registered but not approved yet
- Admin needs to approve in approval panel

### "Admin access required" error
- User trying to access admin endpoints
- Check user role: `SELECT email, role FROM users;`

### Emails not sending
- Check SMTP configuration in `.env`
- Check email service logs
- Emails are optional - system works without them

## Summary

✅ Website login/signup buttons redirect to app  
✅ Users must register and be approved by admin  
✅ Admin receives notifications  
✅ Complete audit trail  
✅ Professional user experience  
✅ Secure by default  

**The website and application are now fully integrated with a professional onboarding flow!** 🎯

