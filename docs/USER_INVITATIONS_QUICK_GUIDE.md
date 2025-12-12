# User Invitations - Quick Guide

## Yes! You Can Invite Users Right Now

VeriCase already has a **complete invitation system** built in. Here's how to use it:

---

## API Endpoints (Already Built)

### 1. Create Invitation (Admin Only)

```http
POST /users/invitations
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "email": "newuser@example.com",
  "role": "viewer"  // viewer, editor, or admin
}
```

**Response:**
```json
{
  "token": "abc123def456...",
  "email": "newuser@example.com",
  "role": "viewer",
  "expires_at": "2025-12-19T05:44:00Z",
  "created_at": "2025-12-12T05:44:00Z"
}
```

### 2. List All Invitations

```http
GET /users/invitations
Authorization: Bearer {admin_token}
```

### 3. Revoke Invitation

```http
DELETE /users/invitations/{token}
Authorization: Bearer {admin_token}
```

### 4. Validate Invitation (Public)

```http
GET /users/invitations/{token}/validate
```

### 5. Accept Invitation (Public)

```http
POST /users/invitations/{token}/accept
Content-Type: application/json

{
  "password": "NewUser123!"
}
```

---

## Quick Usage Examples

### Example 1: Invite a New Team Member

```bash
# As admin, create invitation
curl -X POST http://localhost:8010/users/invitations \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "colleague@firm.com",
    "role": "editor"
  }'

# Returns:
{
  "token": "abc123def456...",
  "email": "colleague@firm.com",
  "role": "editor",
  "expires_at": "2025-12-19T05:44:00Z"
}
```

### Example 2: Share Invitation Link

Send the user this URL:
```
https://your-vericase-domain.com/register?invite=abc123def456...
```

Or for local development:
```
http://localhost:8010/ui/register.html?invite=abc123def456...
```

### Example 3: User Accepts Invitation

```javascript
// In your register.html
const urlParams = new URLSearchParams(window.location.search);
const inviteToken = urlParams.get('invite');

if (inviteToken) {
    // Validate invitation first
    const validation = await fetch(`/users/invitations/${inviteToken}/validate`);
    const inviteData = await validation.json();
    
    // Show email and role
    document.getElementById('invite-email').textContent = inviteData.email;
    document.getElementById('invite-role').textContent = inviteData.role;
    
    // When user sets password
    const response = await fetch(`/users/invitations/${inviteToken}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: userPassword })
    });
    
    const result = await response.json();
    // User is now logged in with result.token
    localStorage.setItem('token', result.token);
    window.location.href = '/ui/dashboard.html';
}
```

---

## UI Integration Example

### Admin Panel - Invite Users

Add to your `admin-users.html`:

```html
<div class="invite-section">
    <h3>Invite New User</h3>
    <form id="invite-form">
        <div class="form-group">
            <label>Email</label>
            <input type="email" id="invite-email" required>
        </div>
        <div class="form-group">
            <label>Role</label>
            <select id="invite-role">
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
            </select>
        </div>
        <button type="submit">Send Invitation</button>
    </form>
    
    <h4>Active Invitations</h4>
    <table id="invitations-table">
        <thead>
            <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Expires</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="invitations-list"></tbody>
    </table>
</div>

<script>
async function sendInvitation() {
    const email = document.getElementById('invite-email').value;
    const role = document.getElementById('invite-role').value;
    
    const response = await fetch('/users/invitations', {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${getToken()}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email, role })
    });
    
    if (response.ok) {
        const invitation = await response.json();
        
        // Show invitation link
        const inviteUrl = `${window.location.origin}/ui/register.html?invite=${invitation.token}`;
        
        alert(`Invitation sent! Share this link:\n${inviteUrl}`);
        
        // Or copy to clipboard
        navigator.clipboard.writeText(inviteUrl);
        showNotification('Invitation link copied to clipboard!');
        
        // Reload invitations list
        loadInvitations();
    }
}

async function loadInvitations() {
    const response = await fetch('/users/invitations', {
        headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    
    const invitations = await response.json();
    
    const tbody = document.getElementById('invitations-list');
    tbody.innerHTML = invitations.map(inv => `
        <tr>
            <td>${inv.email}</td>
            <td>${inv.role}</td>
            <td>${new Date(inv.expires_at).toLocaleDateString()}</td>
            <td>
                <button onclick="copyInviteLink('${inv.token}')">Copy Link</button>
                <button onclick="revokeInvite('${inv.token}')">Revoke</button>
            </td>
        </tr>
    `).join('');
}

function copyInviteLink(token) {
    const url = `${window.location.origin}/ui/register.html?invite=${token}`;
    navigator.clipboard.writeText(url);
    showNotification('Invitation link copied!');
}

async function revokeInvite(token) {
    if (!confirm('Revoke this invitation?')) return;
    
    await fetch(`/users/invitations/${token}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    
    loadInvitations();
}

document.getElementById('invite-form').addEventListener('submit', (e) => {
    e.preventDefault();
    sendInvitation();
});

// Load on page load
loadInvitations();
</script>
```

### Registration Page with Invitation

Update your `register.html`:

```html
<div id="invitation-section" style="display:none;">
    <div class="invitation-banner">
        <h2>You've been invited to VeriCase!</h2>
        <p>Email: <strong id="invite-email"></strong></p>
        <p>Role: <strong id="invite-role"></strong></p>
    </div>
</div>

<form id="register-form">
    <input type="email" id="email" readonly>
    <input type="password" id="password" placeholder="Choose a password" required>
    <input type="password" id="confirm-password" placeholder="Confirm password" required>
    <button type="submit">Create Account</button>
</form>

<script>
const urlParams = new URLSearchParams(window.location.search);
const inviteToken = urlParams.get('invite');

if (inviteToken) {
    // Show invitation section
    document.getElementById('invitation-section').style.display = 'block';
    
    // Validate invitation
    fetch(`/users/invitations/${inviteToken}/validate`)
        .then(res => res.json())
        .then(data => {
            document.getElementById('invite-email').textContent = data.email;
            document.getElementById('invite-role').textContent = data.role;
            document.getElementById('email').value = data.email;
        })
        .catch(err => {
            alert('Invalid or expired invitation link');
            window.location.href = '/ui/login.html';
        });
}

document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    
    if (password !== confirmPassword) {
        alert('Passwords do not match');
        return;
    }
    
    if (inviteToken) {
        // Accept invitation
        const response = await fetch(`/users/invitations/${inviteToken}/accept`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        
        if (response.ok) {
            const result = await response.json();
            localStorage.setItem('token', result.token);
            window.location.href = '/ui/dashboard.html';
        } else {
            alert('Failed to accept invitation');
        }
    } else {
        // Normal registration flow
        // ... existing registration code ...
    }
});
</script>
```

---

## Features Already Included

✅ **Invitation Tokens** - Unique secure tokens
✅ **Expiration** - Invitations expire after 7 days
✅ **Role Assignment** - Assign role during invitation
✅ **Email Validation** - Prevents duplicate invitations
✅ **Admin Only** - Only admins can create invitations
✅ **Public Accept** - Anyone with token can accept

---

## Testing

### 1. Create Invitation
```bash
curl -X POST http://localhost:8010/users/invitations \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "role": "editor"}'
```

### 2. List Invitations
```bash
curl http://localhost:8010/users/invitations \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 3. Validate Token
```bash
curl http://localhost:8010/users/invitations/{token}/validate
```

### 4. Accept Invitation
```bash
curl -X POST http://localhost:8010/users/invitations/{token}/accept \
  -H "Content-Type: application/json" \
  -d '{"password": "NewUser123!"}'
```

---

## Email Integration (Optional)

To send invitation emails automatically, integrate with an email service:

```python
# In users.py, after creating invitation:

from .email_service import email_service

# Send invitation email
invite_url = f"{settings.BASE_URL}/register?invite={token}"
email_service.send_invitation_email(
    to_email=email_lower,
    invite_url=invite_url,
    invited_by=admin.display_name or admin.email,
    role=role.value
)
```

---

## Security Features

1. **Token-based** - Secure random tokens
2. **Time-limited** - 7-day expiration
3. **Single-use** - Token deleted after acceptance
4. **Admin-only creation** - Prevents unauthorized invites
5. **Email uniqueness** - No duplicate invitations
6. **Password validation** - 8-128 character requirement

---

## Summary

### You Already Have:
- ✅ `/users/invitations` - Create invitation
- ✅ `/users/invitations` - List invitations  
- ✅ `/users/invitations/{token}` - Revoke
- ✅ `/users/invitations/{token}/validate` - Validate
- ✅ `/users/invitations/{token}/accept` - Accept

### To Start Using:
1. **Admin creates invitation** via API
2. **Share invitation link** with new user
3. **User clicks link** and sets password
4. **User is logged in** automatically

### The system is ready to use RIGHT NOW! 🎉
