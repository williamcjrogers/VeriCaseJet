# Install AWS Load Balancer Controller
helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system --set clusterName=vericase-cluster --set region=eu-west-2 --set vpcId=<YOUR_VPC_ID>

# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Wait for cert-manager
Start-Sleep -Seconds 60

# Deploy ingress
kubectl apply -f pst-analysis-engine/k8s-ingress.yaml

# Check status
kubectl get ingress -n vericase
kubectl get certificate -n vericase
kubectl describe certificate vericase-tls -n vericase
