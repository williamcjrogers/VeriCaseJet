# 🔐 How to Change RDS Database Password

## Step-by-Step Instructions

Your database password was exposed in the `.kilocode/mcp.json` file:
- **Database:** database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com
- **Old Password:** Sunnyday8?!
- **Username:** VericaseDocsAdmin

---

## 🎯 Change Password via AWS Console

### Step 1: Navigate to RDS

1. Go to AWS Console: https://console.aws.amazon.com/rds/
2. Click on **"Databases"** in the left sidebar
3. You'll see a list of your databases

### Step 2: Select Your Database

1. Click on **database-1** (or the database ID that matches your connection string)
2. This will open the database details page

### Step 3: Modify the Database

1. Click the orange **"Modify"** button at the top right
2. Scroll down to find the **"Settings"** section

### Step 4: Change the Password

1. Find **"Master password"** field
2. You have two options:
   - **Self managed:** Type in a new strong password
   - **Manage with AWS Secrets Manager:** Let AWS manage it (recommended)

**For self-managed password:**
- Click **"Self managed"**
- Enter a strong new password (minimum 8 characters)
- Example: `NewSecure2025Pass!word#123`
- Re-type to confirm

**Recommended password requirements:**
- At least 16 characters
- Mix of uppercase, lowercase, numbers, symbols
- Avoid common words
- Use a password manager to generate it

### Step 5: Apply the Change

1. Scroll to the bottom of the page
2. Under **"Scheduling of modifications"**:
   - Select **"Apply immediately"** (recommended for security)
   - OR **"Apply during maintenance window"** (if you can wait)

3. Click the orange **"Modify DB instance"** button

### Step 6: Confirm

1. Review the summary of changes
2. Click **"Modify DB instance"** to confirm

---

## ⚠️ IMPORTANT WARNINGS

### Application Downtime
- If you select "Apply immediately", your application will have **brief downtime** (2-5 minutes)
- The database will restart to apply the new password
- Plan accordingly!

### Update Application Configuration
After changing the password, you MUST update:

1. **Local `.aws/credentials` or connection strings**
2. **Environment variables** on any servers
3. **AWS Secrets Manager** (if you're using it)
4. **Application configuration files** (but don't commit them to git!)
5. **Kubernetes secrets** (if using EKS)
6. **Docker environment** files

---

## 🔧 Update Local Connection String

After changing the password, update your connection string:

**Old format:**
```
postgresql://VericaseDocsAdmin:Sunnyday8?!@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres
```

**New format:**
```
postgresql://VericaseDocsAdmin:YOUR_NEW_PASSWORD_HERE@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres
```

### Where to Update:

```powershell
# Update PowerShell profile
notepad $PROFILE

# Add this line with NEW password:
$env:POSTGRES_CONNECTION_STRING = "postgresql://VericaseDocsAdmin:YOUR_NEW_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres"
```

---

## ✅ Verify Connection Works

After changing the password and updating your configuration:

```powershell
# Test connection (if you have psql installed)
psql "postgresql://VericaseDocsAdmin:YOUR_NEW_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres" -c "SELECT version();"
```

Or restart your application and check the logs for connection errors.

---

## 🔒 Best Practice: Use AWS Secrets Manager

Instead of managing passwords manually, consider using AWS Secrets Manager:

1. When modifying the database, select **"Manage with AWS Secrets Manager"**
2. AWS will automatically generate and rotate strong passwords
3. Your application can fetch the password programmatically
4. No need to hardcode passwords anywhere

**Benefits:**
- Automatic password rotation
- Encrypted storage
- Audit trail of access
- No passwords in code or config files

---

## 📋 What to Update After Password Change

- [ ] AWS RDS password changed
- [ ] Local environment variables updated
- [ ] Application configuration updated
- [ ] Kubernetes secrets updated (if applicable)
- [ ] Application restarted and tested
- [ ] Database connection verified
- [ ] Old password documented as "compromised" in password manager

---

## 🆘 If Something Goes Wrong

If you change the password and your application breaks:

1. **Check CloudWatch logs** for connection errors
2. **Verify the new password** is correct (typos are common)
3. **Restart your application** after updating configuration
4. **Check security groups** allow connections
5. If stuck, you can change the password again in AWS Console

---

**Time Required:** 10 minutes + application restart time

**Downtime:** 2-5 minutes during database restart (if applying immediately)

**Difficulty:** Easy (just follow the steps carefully)
