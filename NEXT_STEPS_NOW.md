# 🎯 DO THIS RIGHT NOW - You're in AWS Console!

I can see you're already viewing the VericaseDocsAdmin user in AWS Console. Perfect! Follow these steps **IN ORDER**:

---

## ✅ YOU ARE HERE: AWS Console → IAM → VericaseDocsAdmin

### STEP 1: Remove Quarantine Policy (2 minutes)

1. Click the **"Permissions"** tab at the top of the page
2. Scroll down to the policies list
3. Find **"AWSCompromisedKeyQuarantineV3"** 
4. Check the box next to it OR click the X button
5. Click **"Detach"** or **"Remove"**
6. Confirm the removal

---

### STEP 2: Create NEW Access Key (3 minutes)

1. Click the **"Security credentials"** tab at the top
2. Scroll down to **"Access keys"** section (you can see both keys in your screenshot)
3. Click the blue **"Create access key"** button
4. Select: **"Command Line Interface (CLI)"**
5. Check the acknowledgment box
6. Click **"Next"**
7. (Optional) Add description: "Rotated after exposure incident"
8. Click **"Create access key"**
9. **⚠️ CRITICAL:** Click **"Download .csv file"** immediately
10. Also copy/paste both the Access Key ID and Secret Access Key to a secure location
11. **DO NOT CLOSE THIS WINDOW** until keys are saved!

---

### STEP 3: Update Local Credentials (2 minutes)

Open PowerShell and run:

```powershell
# Open credentials file
notepad $HOME\.aws\credentials
```

Replace the old keys with NEW keys from Step 2:

```ini
[default]
aws_access_key_id = YOUR_NEW_ACCESS_KEY_ID_HERE
aws_secret_access_key = YOUR_NEW_SECRET_ACCESS_KEY_HERE
region = eu-west-2
```

Save and close notepad.

---

### STEP 4: Test New Keys (1 minute)

In PowerShell, run:

```powershell
aws sts get-caller-identity
```

**Expected output:**
```json
{
    "UserId": "AIDAXU6HVWBT...",
    "Account": "526015377510",
    "Arn": "arn:aws:iam::526015377510:user/VericaseDocsAdmin"
}
```

If you see this WITHOUT errors, proceed to Step 5.

---

### STEP 5: Delete Exposed Key (2 minutes)

**ONLY proceed if Step 4 worked!**

1. Back in AWS Console → Security credentials tab
2. Find the exposed key: **AKIAXU6HVWBTKU4CVBUA** (currently shown as Active in your screenshot)
3. Click **"Actions"** dropdown next to it
4. Select **"Deactivate"** (safety measure)
5. Wait 10 seconds
6. Click **"Actions"** again → **"Delete"**
7. Type: `AKIAXU6HVWBTKU4CVBUA` to confirm
8. Click **"Delete"**

---

### STEP 6: Enable MFA (5 minutes) - IMPORTANT!

Still in Security credentials tab:

1. Scroll to **"Multi-factor authentication (MFA)"** section
2. Click **"Assign MFA device"**
3. Device name: `VericaseDocsAdmin-MFA`
4. MFA device type: **"Authenticator app"**
5. Click **"Next"**
6. You'll see a QR code
7. Open your phone's authenticator app (Google Authenticator, Authy, Microsoft Authenticator, 1Password, etc.)
8. Scan the QR code
9. The app will show a 6-digit code that changes every 30 seconds
10. Enter the current code in "MFA code 1"
11. Wait for it to change, then enter the next code in "MFA code 2"
12. Click **"Add MFA"**

✅ **Success indicator:** You should see "Assigned MFA device" in the console

---

## 🔥 AFTER AWS IS COMPLETE - Run These Commands

Once you've completed Steps 1-6 above, open PowerShell and run:

```powershell
# Navigate to project
cd C:\Users\William\Documents\Projects\VeriCaseJet_canonical

# Verify AWS credentials work
aws sts get-caller-identity

# Clean git history to remove exposed credentials
.\cleanup-git-history.ps1
```

The cleanup script will:
- Create a backup branch
- Remove the `.kilocode/mcp.json` file from ALL git history
- Prompt you to force push to GitHub

---

## 📋 Other Credentials to Rotate (Do after AWS)

After AWS is secured, you still need to rotate:

### 1. GitHub Personal Access Token
- Go to: https://github.com/settings/tokens
- Delete the exposed token
- Create a new one

### 2. Qdrant API Key  
- Go to: https://cloud.qdrant.io/
- Delete the exposed key
- Generate a new one

### 3. RDS Database Password
- AWS Console → RDS → database-1 → Modify
- Change password
- Apply immediately

---

## ❓ Stuck or Need Help?

If you get an error at any step, STOP and let me know:
- Which step you're on
- The exact error message
- A screenshot if possible

---

**Time estimate for AWS steps:** 15 minutes  
**Status:** Step 1 of 6 - Remove Quarantine Policy

---

**START WITH STEP 1 NOW!**
