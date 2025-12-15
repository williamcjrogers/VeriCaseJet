# AWS and SSH MCP Servers Configuration Guide

This guide will help you configure the AWS and SSH MCP (Model Context Protocol) servers that have been added to your VS Code/Cline setup.

## Overview

The following MCP servers have been added:

1. **AWS KB Retrieval Server** - For retrieving data from AWS Knowledge Bases
2. **AWS Server** - For general AWS service interactions
3. **SSH/SSHFS Server** - For SSH connections and remote file system access

## AWS Configuration

### Prerequisites

You need AWS credentials to use the AWS MCP servers. These can be obtained from your AWS Console.

### Step 1: Get Your AWS Credentials

1. Log in to the [AWS Console](https://console.aws.amazon.com/)
2. Navigate to IAM (Identity and Access Management)
3. Go to "Users" and select your user (or create a new one)
4. Click on "Security credentials" tab
5. Click "Create access key"
6. Choose "Command Line Interface (CLI)" as the use case
7. Save both:
   - **Access Key ID**
   - **Secret Access Key**

### Step 2: Configure AWS MCP Servers (Recommended: AWS Profiles)

This repo includes a setup script that generates a workspace-local MCP config using `AWS_PROFILE` + `AWS_REGION`
(avoids hardcoding access keys into JSON files).

1) Configure a profile:
```powershell
aws configure --profile default
```

2) Generate `.vscode/mcp.json`:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-mcp-servers.ps1 -Force
```

### Step 3: Common AWS Regions

- `us-east-1` - US East (N. Virginia)
- `us-west-2` - US West (Oregon)
- `eu-west-1` - Europe (Ireland)
- `eu-central-1` - Europe (Frankfurt)
- `ap-southeast-1` - Asia Pacific (Singapore)
- `ap-northeast-1` - Asia Pacific (Tokyo)

## SSH Configuration

### Workspace SSH MCP Server (Paramiko)

This repo’s SSH MCP server runs commands over SSH using Paramiko.

It reads:
- `SSH_HOST`, `SSH_USER`, `SSH_PORT`
- `SSH_PRIVATE_KEY_PATH`
- `SSH_STRICT_HOST_KEY_CHECKING` (recommended `true`)
- `SSH_KNOWN_HOSTS_PATH` (path to an OpenSSH `known_hosts` file)

If strict host key checking is enabled, you must prime `known_hosts` first.

Windows helper (recommended):
```powershell
powershell -ExecutionPolicy Bypass -File .\vericase\ops\setup-ssh.ps1
```

### Common SSH Use Cases

1. **Connect to EC2 instances**
2. **Access remote development servers**
3. **Browse remote file systems**
4. **Execute commands on remote machines**

### SSH Key Setup (Recommended)

For secure SSH connections, set up SSH keys:

1. Generate an SSH key pair (if you don't have one):
   ```powershell
   ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
   ```

2. Copy your public key to the remote server:
   ```powershell
   ssh-copy-id user@remote-server
   ```

3. Or manually add it to `~/.ssh/authorized_keys` on the remote server

## Available Capabilities

### AWS KB Retrieval Server

- **retrieve_from_aws_kb**: Retrieve information from AWS Knowledge Bases
  - Query knowledge bases
  - Get relevant documents
  - Semantic search across your AWS KB

### AWS Server

- Interact with various AWS services
- Manage AWS resources
- Query AWS infrastructure
- Access AWS APIs

### SSH/SSHFS Server

- Connect to remote servers
- Access remote file systems
- Execute commands remotely
- Browse and manage remote files

## Testing Your Configuration

After configuration, reload VS Code or restart the MCP servers:

1. Open VS Code Command Palette (Ctrl+Shift+P)
2. Run: "MCP: Restart Servers"
3. Or run: "Developer: Reload Window"

## Security Best Practices

### AWS Credentials

1. **Never commit credentials to version control**
2. **Use IAM roles when possible** (especially for EC2 instances)
3. **Rotate access keys regularly**
4. **Use the principle of least privilege** - only grant necessary permissions
5. **Consider using AWS SSO** for better security
6. **Enable MFA** on your AWS account

### SSH Security

1. **Use SSH keys instead of passwords**
2. **Disable password authentication** on servers
3. **Use strong passphrases** for SSH keys
4. **Keep private keys secure** - never share them
5. **Use SSH config file** for connection management
6. **Regularly update SSH client and server**

## Troubleshooting

### AWS Connection Issues

1. Verify credentials are correct
2. Check AWS region is correct
3. Ensure IAM user has necessary permissions
4. Check internet connectivity
5. Verify MCP server is running (check logs)

### SSH Connection Issues

1. Verify SSH server is accessible
2. Check firewall rules
3. Verify SSH key permissions (should be 600)
4. Check SSH config file for errors
5. Test connection manually: `ssh user@host`

## Additional Configuration

### Using AWS Profiles

If you have multiple AWS accounts, you can configure AWS CLI profiles:

```powershell
aws configure --profile project1
aws configure --profile project2
```

Then reference the profile in your MCP configuration using:
```json
"env": {
  "AWS_PROFILE": "project1"
}
```

### SSH Config File

Create/edit `~/.ssh/config` for easier SSH access:

```
Host myserver
    HostName 192.168.1.100
    User myuser
    IdentityFile ~/.ssh/id_rsa
    Port 22

Host ec2-prod
    HostName ec2-xx-xx-xx-xx.compute.amazonaws.com
    User ec2-user
    IdentityFile ~/.ssh/aws-key.pem
```

## Next Steps

1. Configure your AWS credentials in the MCP settings file
2. Set up SSH keys if not already done
3. Reload VS Code to activate the new MCP servers
4. Test the connections by asking Cline to interact with AWS or SSH resources

## Support

For issues or questions:
- Check the [MCP documentation](https://modelcontextprotocol.io/)
- Review AWS IAM permissions
- Check SSH connection logs
- Verify MCP server logs in VS Code output panel

## Example Commands

Once configured, you can ask Cline:

- "Retrieve information from AWS Knowledge Base about [topic]"
- "Connect to my EC2 instance and check the logs"
- "List files on my remote server at /var/www"
- "What AWS resources are running in us-east-1?"
