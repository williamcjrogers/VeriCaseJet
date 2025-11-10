# AWS App Runner Quick Start for VeriCase

## ✅ Your code is now on GitHub!
Branch: `claude/fix-ther-011CUxtpMTDsdgMgoEB4Y5Zg`

## 🚀 Deploy in 5 Minutes:

### 1. Go to AWS App Runner Console
https://console.aws.amazon.com/apprunner

### 2. Click "Create service"

### 3. Source configuration:
- **Repository type**: Source code repository
- **Provider**: GitHub
- **Connection**: Create new (or use existing)
- **Repository**: `williamcjrogers/VeriCase-Analysis`
- **Branch**: `claude/fix-ther-011CUxtpMTDsdgMgoEB4Y5Zg` (or merge to main first)
- **Source directory**: `/`

### 4. Deployment settings:
- ✅ **Automatic deployment** (IMPORTANT!)
- **Configuration source**: Configuration file
- **Path**: `apprunner.yaml`

### 5. Click through to Service settings and add these environment variables:

```
# Generate this:
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">

# Your existing keys:
OPENAI_API_KEY=<your-key>
ANTHROPIC_API_KEY=<your-key>
GEMINI_API_KEY=<your-key>
GROK_API_KEY=<your-key>

# Email (use your Gmail):
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=<your-gmail-app-password>
EMAIL_FROM=noreply@vericase.com

# Admin account:
ADMIN_EMAIL=admin@vericase.com
ADMIN_PASSWORD=<choose-strong-password>

# You'll add these after creating AWS resources:
DATABASE_URL=<will-get-from-RDS>
AWS_ACCESS_KEY_ID=<will-get-from-IAM>
AWS_SECRET_ACCESS_KEY=<will-get-from-IAM>
AWS_STORAGE_BUCKET_NAME=vericase-production
```

### 6. Create & Deploy!

## 🔧 Required AWS Resources (Create these first):

### RDS PostgreSQL:
1. Go to RDS → Create database
2. Choose PostgreSQL, Free tier
3. DB name: `vericase`
4. Note the endpoint for DATABASE_URL

### S3 Bucket:
1. Go to S3 → Create bucket
2. Name: `vericase-production`
3. Block all public access ✅

### IAM User for S3:
1. Go to IAM → Users → Create
2. Attach policy: `AmazonS3FullAccess`
3. Create access key
4. Save the keys for env variables

## 🌐 After Deployment:

Your app will be live at:
```
https://[your-app-id].awsapprunner.com
```

### Update your website:
1. Login button → `https://[your-app-id].awsapprunner.com/login.html`
2. Signup → `https://[your-app-id].awsapprunner.com/signup.html`

## 💡 Tips:
- First deployment takes ~10 minutes
- Subsequent pushes deploy in ~3 minutes
- Check logs if any issues
- The app auto-scales based on traffic

## 📞 Need Help?
- Check deployment logs in App Runner console
- Review `AWS_DEPLOYMENT_GUIDE.md` for detailed steps
- All errors appear in the Logs tab

---

Ready? Go deploy! 🎉
