# Deploy changes via GitHub
Write-Host "Committing and pushing changes..." -ForegroundColor Green

# Add the modified files
git add ui/admin-settings.html
git add test_all_ai_keys.py

# Commit with message
git commit -m "Add Phi-4 self-hosted model to admin settings interface"

# Push to GitHub
git push origin main

Write-Host "Changes pushed to GitHub!" -ForegroundColor Green
Write-Host "EC2 should auto-update from GitHub deployment" -ForegroundColor Cyan