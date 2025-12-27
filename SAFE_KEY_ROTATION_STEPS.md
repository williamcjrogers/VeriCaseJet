# 🔑 SAFE Access Key Rotation - Step by Step

## ⚠️ **DO NOT DELETE BOTH KEYS!** You'll lose all access!

I can see from your screenshot you have:
- **Key 1:** `AKIAXU6HVWBTHOYC5SA7` - Inactive (safe, old key)
- **Key 2:** `AKIAXU6HVWBTKU4CVBUA` - Active (EXPOSED KEY - must delete)

You can only have 2 access keys maximum. Here's the safe way to rotate:

---

## 🎯 SAFE ROTATION PROCEDURE

### OPTION A: Can You Create a New Key? (Try This First)

1. **First, remove the quarantine policy** (if not already done):
   - Click **"Permissions"** tab
   - Find `AWSCompromisedKeyQuarantineV3`
   - Click to select it, then click **"Detach"**
   - Confirm

2. **Try to create a new key:**
   - Go to **"Security credentials"** tab
   - Click the blue **"Create access key"** button
   
   **If you get an error saying "maximum of 2 keys"**, go to Option B below.

3. **If it works:**
   - Download the new keys immediately
   - Update `~/.aws/credentials` with the NEW keys
   - Test with: `aws sts get-caller-identity`
   - Delete the exposed key `AKIAXU6HVWBTKU4CVBUA`

---

### OPTION B: Can't Create New Key? Delete Old Inactive Key First

If you can't create a third key, here's the safe process:

#### Step 1: Delete the OLD INACTIVE key (Safe to delete)
1. Find: `AKIAXU6HVWBTHOYC5SA7` (Status: Inactive)
2. Click **"Actions"** dropdown
3. Select **"Delete"**
4. Type the access key ID to confirm
5. Click **"Delete"**

✅ **This is SAFE because:**
- It's already Inactive
- You're still using the other key (`AKIAXU6HVWBTKU4CVBUA`)
- You won't lose access

#### Step 2: Now Create a NEW key
1. Click **"Create access key"** button
2. Select: **"Command Line Interface (CLI)"**
3. Check the acknowledgment box
4. Click **"Next"** → **"Create access key"**
5. **IMMEDIATELY** click **"Download .csv file"**
6. Copy both keys to a safe location
7. **DO NOT CLOSE THIS WINDOW** until saved!

#### Step 3: Update Your Local Credentials
Open PowerShell:
```powershell
# Open credentials file
notepad $HOME\.aws\credentials
```

Replace with your NEW keys from Step 2:
```ini
[default]
aws_access_key_id = YOUR_NEW_KEY_FROM_STEP_2
aws_secret_access_key = YOUR_NEW_SECRET_FROM_STEP_2
region = eu-west-2
```

Save and close.

#### Step 4: Test New Keys Work
```powershell
aws sts get-caller-identity
```

**Expected output:**
```json
{
    "Account": "526015377510",
    "Arn": "arn:aws:iam::526015377510:user/VericaseDocsAdmin"
}
```

#### Step 5: Delete the EXPOSED key
**ONLY if Step 4 worked!**

1. Back in AWS Console → Security credentials
2. Find: `AKIAXU6HVWBTKU4CVBUA` (the exposed key)
3. Click **"Actions"** → **"Deactivate"** (safety first)
4. Wait 10 seconds
5. Click **"Actions"** → **"Delete"**
6. Type the access key ID to confirm
7. Click **"Delete"**

---

## ✅ Final Result

You should now have:
- ✅ 1 NEW access key (working in your local credentials)
- ✅ Old inactive key deleted
- ✅ Exposed key deleted
- ✅ AWS CLI working properly

---

## 🚨 IMPORTANT WARNINGS

**DON'T:**
- ❌ Delete both keys at once
- ❌ Delete the active key before having a replacement
- ❌ Close the "Create access key" window before saving keys

**DO:**
- ✅ Always test new keys before deleting old ones
- ✅ Save new keys immediately to a secure location
- ✅ Keep the .csv file in a password manager

---

## 🆘 If Something Goes Wrong

**If you accidentally delete all keys:**
1. You'll need to log in as AWS root user
2. Go to IAM → Users → VericaseDocsAdmin
3. Security credentials → Create new access key
4. This is why you should be careful!

---

**Which option are you going with? Need help with any step?**
