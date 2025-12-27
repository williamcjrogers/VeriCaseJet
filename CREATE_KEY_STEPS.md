# ✅ Creating Your New Access Key - Simple Steps

## You're at the right screen! Here's exactly what to do:

---

## 📋 STEP-BY-STEP:

### 1. Select Use Case
**Select: "Command Line Interface (CLI)"** (It's already highlighted in blue - perfect!)

This is the correct choice because you're using AWS CLI on your local computer.

### 2. Check the acknowledgment box
Scroll down and check the box that says:
☑️ "I understand the above recommendation and want to proceed to create an access key."

### 3. Click "Next"
The blue button at the bottom right.

### 4. Add Description (Optional but recommended)
- Description tag: `Rotated after security incident - Dec 2025`
- This helps you remember why you created this key

### 5. Click "Create access key"
The blue button at the bottom.

### 6. ⚠️ CRITICAL STEP - Save the Keys!

You'll see a screen showing:
- **Access key ID**: AKIAXU6HVWBT... (starts with AKIA)
- **Secret access key**: (long random string)

**Do BOTH of these RIGHT NOW:**
1. Click **"Download .csv file"** button
2. Copy/paste both keys somewhere safe (notepad, password manager)

**⚠️ You will NEVER see the secret access key again after closing this window!**

### 7. Keep Window Open
**DO NOT click "Done" yet!** Keep this window open while you update your local credentials.

---

## 🔧 Next: Update Your Local Credentials

Open a NEW PowerShell window (keep AWS Console open):

```powershell
# Open your AWS credentials file
notepad $HOME\.aws\credentials
```

You'll see something like:
```ini
[default]
aws_access_key_id = AKIAXU6HVWBTKU4CVBUA
aws_secret_access_key = old_secret_here
region = eu-west-2
```

**Replace the old keys with your NEW keys from step 6:**
```ini
[default]
aws_access_key_id = YOUR_NEW_ACCESS_KEY_FROM_STEP_6
aws_secret_access_key = YOUR_NEW_SECRET_FROM_STEP_6
region = eu-west-2
```

Save and close notepad.

---

## ✅ Test Your New Keys Work

In PowerShell, run:
```powershell
aws sts get-caller-identity
```

**Expected output (means it works!):**
```json
{
    "UserId": "AIDAXU6HVWBT...",
    "Account": "526015377510",
    "Arn": "arn:aws:iam::526015377510:user/VericaseDocsAdmin"
}
```

**If you see this output without errors:**
✅ Your new keys work!
✅ Now you can close the AWS Console window (click "Done")
✅ Now you can safely delete the exposed key

---

## 🎯 START NOW:

1. Keep "Command Line Interface (CLI)" selected (already highlighted)
2. Scroll down
3. Check the acknowledgment box
4. Click "Next"

**Let me know when you see the screen with the new keys (after step 5)!**
