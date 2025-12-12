# AWS and SSH MCP Servers - Quick Start

## What Was Added

Three new MCP (Model Context Protocol) servers have been added to your VS Code/Cline setup:

### 1. AWS KB Retrieval Server
- Retrieve information from AWS Knowledge Bases
- Semantic search capabilities
- RAG (Retrieval Augmented Generation) support

### 2. AWS Server
- General AWS service interactions
- Resource management
- Infrastructure queries
- Full AWS API access

### 3. SSH/SSHFS Server
- Remote server connections
- Remote file system access
- Execute commands on remote machines
- Perfect for managing EC2 instances and remote servers

## Quick Configuration Steps

### For AWS (Required for AWS servers to work):

1. **Get AWS Credentials:**
   - Go to AWS Console → IAM → Users → Security Credentials
   - Create Access Key
   - Save the Access Key ID and Secret Access Key

2. **Add Credentials to MCP Settings:**
   - Open: `C:\Users\William\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
   - Find the AWS server entries
   - Replace the empty `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` values with your credentials
   - Update `AWS_REGION` if needed (default is `us-east-1`)

3. **Reload VS Code:**
   - Press `Ctrl+Shift+P`
   - Type: "Developer: Reload Window"
   - Or run: "MCP: Restart Servers"

### For SSH (Works once AWS/servers are accessible):

The SSH server works automatically once configured. You can:
- Connect to any SSH server you have access to
- Use SSH keys for authentication (recommended)
- Access remote file systems

## Testing

Try asking Cline:
- "Show me what AWS MCP capabilities are available"
- "List the tools from the AWS servers"
- "Connect to my EC2 instance at [address]"

## Documentation

For detailed instructions, see: **[docs/MCP_AWS_SSH_SETUP.md](docs/MCP_AWS_SSH_SETUP.md)**

This includes:
- Detailed AWS setup instructions
- SSH key configuration
- Security best practices
- Troubleshooting guide
- Example use cases

## Current MCP Servers

Your VS Code now has access to these MCP servers:

✅ **Sequential Thinking** - Advanced problem-solving
✅ **PostgreSQL** - Database queries
✅ **Filesystem** - Local file access
✅ **Memory** - Knowledge graph storage
✅ **AWS KB Retrieval** - AWS Knowledge Base access (NEW)
✅ **AWS** - AWS service interactions (NEW)
✅ **SSH/SSHFS** - Remote server access (NEW)

## Security Notes

⚠️ **IMPORTANT:**
- Never commit AWS credentials to version control
- Use IAM roles when possible
- Use SSH keys instead of passwords
- Keep credentials secure

## Support

If you encounter issues:
1. Check the detailed guide: `docs/MCP_AWS_SSH_SETUP.md`
2. Review MCP server logs in VS Code Output panel
3. Verify AWS credentials are correct
4. Ensure SSH keys have proper permissions (600)

## What's Next?

1. Add your AWS credentials to enable AWS servers
2. Set up SSH keys if you haven't already
3. Reload VS Code
4. Start using the new capabilities!

---

**Configuration File Location:**
```
C:\Users\William\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json
```

**Detailed Guide:**
```
docs/MCP_AWS_SSH_SETUP.md
```
