#!/bin/bash
# Fix Admin Account - Kubernetes Production
# Run this to diagnose and fix the admin@vericase.com account in Kubernetes

set -e

echo "======================================================================"
echo "VeriCase Admin Account Fix - Kubernetes"
echo "======================================================================"

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found! Install kubectl first."
    exit 1
fi

# Check namespace
NAMESPACE="${VERICASE_NAMESPACE:-vericase}"
echo ""
echo "🔍 Checking namespace: $NAMESPACE"

if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo "❌ Namespace $NAMESPACE not found!"
    echo "   Set VERICASE_NAMESPACE environment variable if using a different namespace"
    exit 1
fi

# Find API pod
echo "🔍 Finding API pod..."
API_POD=$(kubectl get pods -n "$NAMESPACE" -l app=vericase-api -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$API_POD" ]; then
    echo "❌ No VeriCase API pod found in namespace $NAMESPACE"
    echo "   Check your deployment with: kubectl get pods -n $NAMESPACE"
    exit 1
fi

echo "✅ Found API pod: $API_POD"

# Check if fix script exists in pod
echo ""
echo "🔍 Checking for fix script..."
if ! kubectl exec -n "$NAMESPACE" "$API_POD" -- test -f /app/fix_admin_account.py; then
    echo "⚠️  Fix script not found in pod, copying it..."
    kubectl cp "$(dirname "$0")/api/fix_admin_account.py" "$NAMESPACE/$API_POD:/app/fix_admin_account.py"
fi

# Menu for action
echo ""
echo "📋 What would you like to do?"
echo "   1. Fix existing admin@vericase.com account"
echo "   2. Create NEW admin@veri-case.com account (recommended)"
echo "   3. Both (fix old, create new)"
echo ""
read -p "Choice (1/2/3): " choice

echo ""
echo "======================================================================"

case "$choice" in
    1)
        echo "🔧 Running fix on admin@vericase.com..."
        kubectl exec -it -n "$NAMESPACE" "$API_POD" -- python /app/fix_admin_account.py
        ;;
    2)
        echo "🆕 Creating NEW admin@veri-case.com account..."
        # Copy create script if needed
        if ! kubectl exec -n "$NAMESPACE" "$API_POD" -- test -f /app/create_new_admin.py; then
            kubectl cp "$(dirname "$0")/api/create_new_admin.py" "$NAMESPACE/$API_POD:/app/create_new_admin.py"
        fi
        kubectl exec -it -n "$NAMESPACE" "$API_POD" -- python /app/create_new_admin.py
        ;;
    3)
        echo "🔧 Fixing admin@vericase.com..."
        kubectl exec -it -n "$NAMESPACE" "$API_POD" -- python /app/fix_admin_account.py
        echo ""
        echo "🆕 Creating NEW admin@veri-case.com..."
        if ! kubectl exec -n "$NAMESPACE" "$API_POD" -- test -f /app/create_new_admin.py; then
            kubectl cp "$(dirname "$0")/api/create_new_admin.py" "$NAMESPACE/$API_POD:/app/create_new_admin.py"
        fi
        kubectl exec -it -n "$NAMESPACE" "$API_POD" -- python /app/create_new_admin.py
        ;;
    *)
        echo "⚠️  Invalid choice, running fix by default..."
        kubectl exec -it -n "$NAMESPACE" "$API_POD" -- python /app/fix_admin_account.py
        ;;
esac

echo ""
echo "======================================================================"
echo "✅ Fix complete!"
echo "======================================================================"

# Check secrets
echo ""
echo "📋 Checking environment secrets..."
JWT_SECRET_EXISTS=$(kubectl get secret vericase-secrets -n "$NAMESPACE" -o jsonpath='{.data.JWT_SECRET}' 2>/dev/null || echo "")
ADMIN_PASSWORD_EXISTS=$(kubectl get secret vericase-secrets -n "$NAMESPACE" -o jsonpath='{.data.ADMIN_PASSWORD}' 2>/dev/null || echo "")

if [ -z "$JWT_SECRET_EXISTS" ]; then
    echo "⚠️  WARNING: JWT_SECRET not found in vericase-secrets"
    echo "   Create it with:"
    echo "   kubectl create secret generic vericase-secrets \\"
    echo "     --from-literal=JWT_SECRET=\$(openssl rand -hex 32) \\"
    echo "     -n $NAMESPACE"
else
    echo "✅ JWT_SECRET exists in secrets"
fi

if [ -z "$ADMIN_PASSWORD_EXISTS" ]; then
    echo "⚠️  WARNING: ADMIN_PASSWORD not found in vericase-secrets"
    echo "   Add it with:"
    echo "   kubectl patch secret vericase-secrets -n $NAMESPACE \\"
    echo "     --type merge -p '{\"data\":{\"ADMIN_PASSWORD\":\"'\$(echo -n 'YourSecurePassword123!' | base64)'\"}}"
else
    echo "✅ ADMIN_PASSWORD exists in secrets"
fi

echo ""
echo "📋 Next Steps:"
echo "   1. Try logging in with admin@vericase.com"
echo "   2. If login fails, check API logs:"
echo "      kubectl logs -n $NAMESPACE $API_POD --tail 50"
echo "   3. Verify JWT_SECRET is configured correctly"
echo ""
