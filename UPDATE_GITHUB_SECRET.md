# Update GitHub Secret

Go to: https://github.com/williamcjrogers/VeriCaseJet/settings/secrets/actions

Update **EC2_INSTANCE_ID** to:
```
i-0913d878182fa803c
```

This instance has SSM agent installed and can receive deployment commands.

**Instance Details:**
- IP: 35.179.167.235
- SSM Agent: ✅ Online
- Platform: Amazon Linux

**Production Instance (i-0ade6dff1811bdbcb):**
- IP: 18.130.216.34
- SSM Agent: ❌ Not installed
- Cannot use for auto-deployment

---

After updating the secret, push any commit to trigger auto-deployment.
