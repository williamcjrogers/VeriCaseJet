# Azure AD MCP Server

This MCP (Model Context Protocol) server provides tools for interacting with Azure Active Directory through the Microsoft Graph API.

## Features

- **List Users**: Retrieve Azure AD users with filtering and pagination
- **Get User Details**: Get comprehensive information about specific users
- **List Groups**: Retrieve Azure AD groups with filtering
- **Get Group Members**: List members of specific groups
- **List Applications**: Retrieve Azure AD applications (service principals)

## Prerequisites

1. **Azure AD Application Registration**:
   - Go to [Azure Portal](https://portal.azure.com)
   - Navigate to "Azure Active Directory" > "App registrations"
   - Click "New registration"
   - Choose a name and register the application

2. **API Permissions**:
   - In your app registration, go to "API permissions"
   - Add the following Microsoft Graph permissions:
     - `User.Read.All` (for reading user information)
     - `Group.Read.All` (for reading group information)
     - `Application.Read.All` (for reading application information)
   - Grant admin consent for these permissions

3. **Client Secret**:
   - In your app registration, go to "Certificates & secrets"
   - Create a new client secret
   - Copy the secret value (you won't be able to see it again)

## Configuration

Update your MCP settings file with the following environment variables:

```json
{
  "mcpServers": {
    "azure-ad": {
      "command": "node",
      "args": ["path/to/azure-ad-server/build/index.js"],
      "env": {
        "AZURE_TENANT_ID": "your-tenant-id",
        "AZURE_CLIENT_ID": "your-client-id",
        "AZURE_CLIENT_SECRET": "your-client-secret"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### Required Environment Variables

- `AZURE_TENANT_ID`: Your Azure AD tenant ID
- `AZURE_CLIENT_ID`: Your application (client) ID
- `AZURE_CLIENT_SECRET`: Your client secret

## Usage Examples

Once configured, you can use the following commands in your AI assistant:

### List Users
```
List Azure AD users in my organization
```
```javascript
// With filtering
list_users({
  filter: "department eq 'IT'",
  top: 50,
  select: "displayName,userPrincipalName,mail"
})
```

### Get User Details
```
Get details for user john.doe@company.com
```
```javascript
get_user({
  user_id: "john.doe@company.com"
})
```

### List Groups
```
Show me all security groups
```
```javascript
list_groups({
  filter: "groupTypes/any(c:c eq 'Unified')",
  top: 25
})
```

### Get Group Members
```
Who are the members of the "Developers" group?
```
```javascript
get_group_members({
  group_id: "group-object-id",
  top: 100
})
```

### List Applications
```
Show me registered applications
```
```javascript
list_applications({
  filter: "startswith(displayName,'MyApp')",
  top: 10
})
```

## API Reference

### list_users
Lists Azure AD users with optional filtering.

**Parameters:**
- `filter` (string, optional): OData filter expression
- `top` (number, optional): Maximum results (1-999, default: 100)
- `select` (string, optional): Comma-separated properties to return

### get_user
Gets detailed information about a specific user.

**Parameters:**
- `user_id` (string, required): User ID or userPrincipalName

### list_groups
Lists Azure AD groups with optional filtering.

**Parameters:**
- `filter` (string, optional): OData filter expression
- `top` (number, optional): Maximum results (1-999, default: 100)

### get_group_members
Gets members of a specific group.

**Parameters:**
- `group_id` (string, required): Group object ID
- `top` (number, optional): Maximum results (1-999, default: 100)

### list_applications
Lists Azure AD applications (service principals).

**Parameters:**
- `filter` (string, optional): OData filter expression
- `top` (number, optional): Maximum results (1-999, default: 100)

## OData Filtering Examples

- Users in IT department: `department eq 'IT'`
- Users whose name starts with "John": `startswith(displayName,'John')`
- Security groups only: `groupTypes/any(c:c eq 'Unified')`
- Applications with specific prefix: `startswith(displayName,'MyApp')`
- Enabled users only: `accountEnabled eq true`

## Security Notes

- This server uses application permissions, not delegated permissions
- All operations are read-only (no create/update/delete operations)
- Credentials are stored securely in your MCP configuration
- API permissions are limited to read operations only

## Troubleshooting

### Authentication Errors
- Verify your tenant ID, client ID, and client secret are correct
- Ensure the application has the required API permissions
- Check that admin consent has been granted for the permissions

### Permission Errors
- Confirm your Azure AD application has the necessary permissions
- Some operations may require additional permissions beyond the defaults

### Network Issues
- Ensure your firewall allows outbound connections to `graph.microsoft.com`
- Check for proxy settings if you're behind a corporate firewall

## Development

To modify or extend this server:

1. Install dependencies: `npm install`
2. Make changes to `src/index.ts`
3. Build: `npm run build`
4. Test: `npm start`

## License

This project is licensed under the ISC License.
