# AWS Infrastructure Setup for TTT2 EKS Deployment

This guide covers the one-time AWS infrastructure provisioning needed before deploying the K8s manifests.

## Prerequisites

- AWS CLI v2 configured for `ap-northeast-2`
- `eksctl`, `kubectl`, `helm`, Docker installed locally

## Step 1: Create ECR Repositories

Two repos needed (backend + frontend):

```bash
aws ecr create-repository --repository-name ttt2-backend --region ap-northeast-2
aws ecr create-repository --repository-name ttt2-frontend --region ap-northeast-2
```

After creation, note the registry URI (e.g. `123456789.dkr.ecr.ap-northeast-2.amazonaws.com`) and update:
- `k8s/backend/deployment.yaml` — replace `<account-id>` and `<region>` in the image field
- `k8s/frontend/deployment.yaml` — same

## Step 2: Create EKS Cluster

```bash
eksctl create cluster \
  --name ttt2-cluster \
  --region ap-northeast-2 \
  --version 1.29 \
  --nodegroup-name ttt2-nodes \
  --node-type t3.small \
  --nodes 2 \
  --managed
```

Takes ~15 minutes. Creates the VPC, subnets, and node group automatically.

## Step 3: Enable IRSA (IAM Roles for Service Accounts)

Required by both the ALB Controller and External Secrets Operator:

```bash
eksctl utils associate-iam-oidc-provider \
  --cluster ttt2-cluster \
  --region ap-northeast-2 \
  --approve
```

## Step 4: Create ElastiCache Redis

```bash
# Get EKS VPC and private subnets
VPC_ID=$(aws eks describe-cluster --name ttt2-cluster --region ap-northeast-2 \
  --query 'cluster.resourcesVpcConfig.vpcId' --output text)

PRIVATE_SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  "Name=tag:aws:cloudformation:logical-id,Values=SubnetPrivate*" \
  --query 'Subnets[].SubnetId' --output text)

# Create subnet group
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name ttt2-redis-subnets \
  --cache-subnet-group-description "TTT2 Redis subnets" \
  --subnet-ids $PRIVATE_SUBNETS \
  --region ap-northeast-2

# Get EKS cluster security group
SG_ID=$(aws eks describe-cluster --name ttt2-cluster --region ap-northeast-2 \
  --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text)

# Create Redis cluster
aws elasticache create-cache-cluster \
  --cache-cluster-id ttt2-redis \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --num-cache-nodes 1 \
  --cache-subnet-group-name ttt2-redis-subnets \
  --security-group-ids $SG_ID \
  --region ap-northeast-2
```

After creation, get the endpoint and update `k8s/configmap.yaml` (`REDIS_URL`):

```bash
aws elasticache describe-cache-clusters --cache-cluster-id ttt2-redis \
  --show-cache-node-info --query 'CacheClusters[0].CacheNodes[0].Endpoint' \
  --region ap-northeast-2
```

## Step 5: Create Secrets Manager Secret

```bash
aws secretsmanager create-secret \
  --name rpcn-client/credentials \
  --secret-string '{"RPCN_USER":"YOUR_USER","RPCN_PASSWORD":"YOUR_PASS"}' \
  --region ap-northeast-2
```

## Step 6: Install AWS Load Balancer Controller

```bash
# Download IAM policy
curl -o alb-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.1/docs/install/iam_policy.json

# Create IAM policy
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://alb-policy.json

# Create IRSA service account
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
eksctl create iamserviceaccount \
  --cluster ttt2-cluster \
  --namespace kube-system \
  --name aws-load-balancer-controller \
  --attach-policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve \
  --region ap-northeast-2

# Install via Helm
helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=ttt2-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

## Step 7: Install External Secrets Operator

```bash
# Create IAM policy for Secrets Manager read access
cat > eso-policy.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:ap-northeast-2:*:secret:rpcn-client/*"
    }
  ]
}
POLICY

aws iam create-policy \
  --policy-name ExternalSecretsPolicy \
  --policy-document file://eso-policy.json

# Create IRSA service account (matches cluster-secret-store.yaml)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
eksctl create iamserviceaccount \
  --cluster ttt2-cluster \
  --namespace external-secrets \
  --name external-secrets-sa \
  --attach-policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/ExternalSecretsPolicy \
  --approve \
  --region ap-northeast-2

# Install via Helm
helm repo add external-secrets https://charts.external-secrets.io
helm repo update
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets \
  --create-namespace \
  --set serviceAccount.create=false \
  --set serviceAccount.name=external-secrets-sa
```

## Step 8: Setup GitHub OIDC for CI/CD

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create OIDC identity provider for GitHub Actions
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  --client-id-list sts.amazonaws.com

# Create IAM role with trust policy for your repo
cat > gh-trust-policy.json << POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/rpcn-client:ref:refs/heads/master"
        }
      }
    }
  ]
}
POLICY

aws iam create-role \
  --role-name GitHubActions-TTT2-Deploy \
  --assume-role-policy-document file://gh-trust-policy.json

# Attach permissions: ECR push + EKS access
aws iam attach-role-policy --role-name GitHubActions-TTT2-Deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser
aws iam attach-role-policy --role-name GitHubActions-TTT2-Deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
```

Then add the role ARN as a GitHub repository secret:
- **Name:** `AWS_ROLE_ARN`
- **Value:** `arn:aws:iam::<ACCOUNT_ID>:role/GitHubActions-TTT2-Deploy`

> Replace `YOUR_ORG/rpcn-client` in the trust policy with your actual GitHub repo path.

## Step 9: Build & Push Initial Image

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY=${ACCOUNT_ID}.dkr.ecr.ap-northeast-2.amazonaws.com

aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin $REGISTRY

docker build -t $REGISTRY/ttt2-backend:latest .
docker push $REGISTRY/ttt2-backend:latest
```

## Step 10: Deploy K8s Manifests

Apply in this order:

```bash
kubectl apply -f k8s/cluster-secret-store.yaml
kubectl apply -f k8s/external-secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/backend/deployment.yaml
kubectl apply -f k8s/backend/service.yaml
kubectl apply -f k8s/frontend/deployment.yaml
kubectl apply -f k8s/frontend/service.yaml
kubectl apply -f k8s/ingress.yaml
```

## Verification

```bash
# Check pods are running
kubectl get pods

# Check external secret synced
kubectl get externalsecret rpcn-credentials
kubectl get secret rpcn-credentials

# Check ingress got an ALB address
kubectl get ingress ttt2-ingress

# Test backend health
ALB=$(kubectl get ingress ttt2-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl http://$ALB/api/health
```

## Cost Estimate (ap-northeast-2)

| Resource | Type | ~Monthly Cost |
|----------|------|--------------|
| EKS control plane | — | $73 |
| EC2 nodes (2x t3.small) | On-demand | ~$38 |
| ElastiCache | cache.t3.micro | ~$13 |
| ALB | — | ~$18 + traffic |
| ECR | Storage | < $1 |
| Secrets Manager | 1 secret | < $1 |
| **Total** | | **~$143/mo** |

## Placeholders to Fill After Provisioning

| File | Placeholder | Replaced With |
|------|------------|---------------|
| `k8s/backend/deployment.yaml` | `<account-id>`, `<region>` | ECR registry URI (Step 1) |
| `k8s/frontend/deployment.yaml` | `<account-id>`, `<region>` | ECR registry URI (Step 1) |
| `k8s/configmap.yaml` | `<elasticache-endpoint>` | Redis endpoint (Step 4) |
| GitHub Secret `AWS_ROLE_ARN` | — | IAM role ARN (Step 8) |
| Step 8 trust policy | `YOUR_ORG/rpcn-client` | Actual GitHub repo path |
