#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import { ClientSecretCredential } from '@azure/identity';
import axios, { AxiosInstance } from 'axios';

// Environment variables from MCP config
const TENANT_ID = process.env.AZURE_TENANT_ID;
const CLIENT_ID = process.env.AZURE_CLIENT_ID;
const CLIENT_SECRET = process.env.AZURE_CLIENT_SECRET;

if (!TENANT_ID || !CLIENT_ID || !CLIENT_SECRET) {
  throw new Error('AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET environment variables are required');
}

interface AzureUser {
  id: string;
  displayName: string;
  userPrincipalName: string;
  mail?: string;
  jobTitle?: string;
  department?: string;
  accountEnabled: boolean;
}

interface AzureGroup {
  id: string;
  displayName: string;
  description?: string;
  mail?: string;
  groupTypes: string[];
  membershipRule?: string;
}

class AzureADServer {
  private server: Server;
  private credential: ClientSecretCredential;
  private graphClient: AxiosInstance;
  private accessToken: string | null = null;

  constructor() {
    this.server = new Server(
      {
        name: 'azure-ad-server',
        version: '0.1.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.credential = new ClientSecretCredential(
      TENANT_ID!,
      CLIENT_ID!,
      CLIENT_SECRET!
    );

    this.graphClient = axios.create({
      baseURL: 'https://graph.microsoft.com/v1.0',
      timeout: 30000,
    });

    this.setupToolHandlers();

    // Error handling
    this.server.onerror = (error) => console.error('[MCP Error]', error);
    process.on('SIGINT', async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  private async getAccessToken(): Promise<string> {
    if (!this.accessToken) {
      const tokenResponse = await this.credential.getToken('https://graph.microsoft.com/.default');
      this.accessToken = tokenResponse.token;
      this.graphClient.defaults.headers.common['Authorization'] = `Bearer ${this.accessToken}`;
    }
    return this.accessToken;
  }

  private setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'list_users',
          description: 'List Azure AD users with optional filtering',
          inputSchema: {
            type: 'object',
            properties: {
              filter: {
                type: 'string',
                description: 'OData filter expression (e.g., "startswith(displayName,\'John\')" or "department eq \'IT\'")',
              },
              top: {
                type: 'number',
                description: 'Maximum number of users to return (default: 100, max: 999)',
                minimum: 1,
                maximum: 999,
              },
              select: {
                type: 'string',
                description: 'Comma-separated list of properties to return (e.g., "displayName,userPrincipalName,mail")',
              },
            },
            required: [],
          },
        },
        {
          name: 'get_user',
          description: 'Get detailed information about a specific Azure AD user',
          inputSchema: {
            type: 'object',
            properties: {
              user_id: {
                type: 'string',
                description: 'User ID or userPrincipalName',
              },
            },
            required: ['user_id'],
          },
        },
        {
          name: 'list_groups',
          description: 'List Azure AD groups with optional filtering',
          inputSchema: {
            type: 'object',
            properties: {
              filter: {
                type: 'string',
                description: 'OData filter expression (e.g., "startswith(displayName,\'Project\')")',
              },
              top: {
                type: 'number',
                description: 'Maximum number of groups to return (default: 100, max: 999)',
                minimum: 1,
                maximum: 999,
              },
            },
            required: [],
          },
        },
        {
          name: 'get_group_members',
          description: 'Get members of a specific Azure AD group',
          inputSchema: {
            type: 'object',
            properties: {
              group_id: {
                type: 'string',
                description: 'Group ID',
              },
              top: {
                type: 'number',
                description: 'Maximum number of members to return (default: 100, max: 999)',
                minimum: 1,
                maximum: 999,
              },
            },
            required: ['group_id'],
          },
        },
        {
          name: 'list_applications',
          description: 'List Azure AD applications (service principals)',
          inputSchema: {
            type: 'object',
            properties: {
              filter: {
                type: 'string',
                description: 'OData filter expression (e.g., "startswith(displayName,\'MyApp\')")',
              },
              top: {
                type: 'number',
                description: 'Maximum number of applications to return (default: 100, max: 999)',
                minimum: 1,
                maximum: 999,
              },
            },
            required: [],
          },
        },
      ],
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      await this.getAccessToken();

      switch (request.params.name) {
        case 'list_users':
          return await this.handleListUsers(request.params.arguments);
        case 'get_user':
          return await this.handleGetUser(request.params.arguments);
        case 'list_groups':
          return await this.handleListGroups(request.params.arguments);
        case 'get_group_members':
          return await this.handleGetGroupMembers(request.params.arguments);
        case 'list_applications':
          return await this.handleListApplications(request.params.arguments);
        default:
          throw new McpError(
            ErrorCode.MethodNotFound,
            `Unknown tool: ${request.params.name}`
          );
      }
    });
  }

  private async handleListUsers(args: any) {
    try {
      const params: any = {
        $top: args?.top || 100,
      };

      if (args?.filter) {
        params.$filter = args.filter;
      }

      if (args?.select) {
        params.$select = args.select;
      }

      const response = await this.graphClient.get('/users', { params });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              users: response.data.value,
              count: response.data.value.length,
            }, null, 2),
          },
        ],
      };
    } catch (error: any) {
      return {
        content: [
          {
            type: 'text',
            text: `Error listing users: ${error.response?.data?.error?.message || error.message}`,
          },
        ],
        isError: true,
      };
    }
  }

  private async handleGetUser(args: any) {
    try {
      const userId = args.user_id;
      const response = await this.graphClient.get(`/users/${userId}`);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(response.data, null, 2),
          },
        ],
      };
    } catch (error: any) {
      return {
        content: [
          {
            type: 'text',
            text: `Error getting user: ${error.response?.data?.error?.message || error.message}`,
          },
        ],
        isError: true,
      };
    }
  }

  private async handleListGroups(args: any) {
    try {
      const params: any = {
        $top: args?.top || 100,
      };

      if (args?.filter) {
        params.$filter = args.filter;
      }

      const response = await this.graphClient.get('/groups', { params });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              groups: response.data.value,
              count: response.data.value.length,
            }, null, 2),
          },
        ],
      };
    } catch (error: any) {
      return {
        content: [
          {
            type: 'text',
            text: `Error listing groups: ${error.response?.data?.error?.message || error.message}`,
          },
        ],
        isError: true,
      };
    }
  }

  private async handleGetGroupMembers(args: any) {
    try {
      const groupId = args.group_id;
      const params: any = {
        $top: args?.top || 100,
      };

      const response = await this.graphClient.get(`/groups/${groupId}/members`, { params });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              members: response.data.value,
            }, null, 2),
          },
        ],
      };
    } catch (error: any) {
      return {
        content: [
          {
            type: 'text',
            text: `Error getting group members: ${error.response?.data?.error?.message || error.message}`,
          },
        ],
        isError: true,
      };
    }
  }

  private async handleListApplications(args: any) {
    try {
      const params: any = {
        $top: args?.top || 100,
      };

      if (args?.filter) {
        params.$filter = args.filter;
      }

      const response = await this.graphClient.get('/servicePrincipals', { params });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              applications: response.data.value,
              count: response.data.value.length,
            }, null, 2),
          },
        ],
      };
    } catch (error: any) {
      return {
        content: [
          {
            type: 'text',
            text: `Error listing applications: ${error.response?.data?.error?.message || error.message}`,
          },
        ],
        isError: true,
      };
    }
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('Azure AD MCP server running on stdio');
  }
}

const server = new AzureADServer();
server.run().catch(console.error);
