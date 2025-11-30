# Update EC2_SSH_KEY GitHub Secret

Go to: https://github.com/williamcjrogers/VeriCaseJet/settings/secrets/actions/EC2_SSH_KEY

Replace the entire content with this key:

```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtz
c2gtZWQyNTUxOQAAACAmVmX1pRHlmW76skUJwR/9TJyLcSAg1py+5o6u5VzztwAA
AIgDlIdvA5SHbwAAAAtzc2gtZWQyNTUxOQAAACAmVmX1pRHlmW76skUJwR/9TJyL
cSAg1py+5o6u5VzztwAAAEAwUQIBATAFBgMrZXAEIgQgxOi1o+v+l9OhlTnqio0Y
QCZWZfWlEeWZbvqyRQnBH/1MnItxICDWnL7mjq7lXPO3AAAAAAECAwQF
-----END OPENSSH PRIVATE KEY-----
```

This is the **VeriCase-Safe.pem** key that the production instance (i-0ade6dff1811bdbcb) uses.

After updating, push any commit to trigger deployment.
