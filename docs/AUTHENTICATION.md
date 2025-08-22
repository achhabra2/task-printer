# Authentication Setup for TaskPrinter MCP Server

The TaskPrinter MCP server supports JWT-based authentication for secure access. This guide explains how to set up and use authentication.

## Overview

The authentication system uses JSON Web Tokens (JWT) with HMAC-SHA256 signing. It's designed for single-user scenarios where you control both the token generation and the MCP server.

## Features

- **Simple JWT authentication** - No complex OAuth flows needed
- **Automatic secret management** - Secret keys are auto-generated and stored securely
- **Configurable expiration** - Tokens expire after 30 days by default
- **Easy token generation** - CLI tool for creating new tokens
- **Optional authentication** - Can be enabled/disabled via environment variables
- **FastMCP Integration** - Custom AuthProvider that works seamlessly with FastMCP

## Quick Start

### 1. Install Dependencies

```bash
uv install
```

### 2. Generate an Authentication Token

```bash
uv run python scripts/generate_token.py
```

This will output something like:
```
Generated JWT token for user 'taskprinter-user':
Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Expires: 30 days from now

To use this token with MCP clients, set it as a Bearer token in the Authorization header:
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

Or set the environment variable:
export TASKPRINTER_AUTH_TOKEN='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

### 3. Start the MCP Server with Authentication

```bash
uv run python mcp_server.py
```

By default, authentication is enabled. The server will log:
```
🔒 JWT Authentication: ENABLED
   Generate tokens with: python scripts/generate_token.py
   Use tokens with: Authorization: Bearer <token>
```

### 4. Use the Token with MCP Clients

Include the token in the `Authorization` header when making requests to the MCP server:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Implementation Details

### Custom AuthProvider

Our implementation uses a custom `TaskPrinterJWTAuth` class that extends FastMCP's `AuthProvider`:

- **Token Verification**: Validates JWT tokens using HMAC-SHA256
- **AccessToken Objects**: Returns proper `AccessToken` objects with expiration info
- **No OAuth Endpoints**: Simple verification-only approach without OAuth complexity
- **Claims Processing**: Extracts user info from JWT claims

### JWT Token Structure

Generated tokens include these standard JWT claims:
- `sub` (subject): User identifier (default: "taskprinter-user")
- `iat` (issued at): Token creation timestamp
- `exp` (expires): Token expiration timestamp (30 days from creation)
- `iss` (issuer): "taskprinter-mcp"
- `aud` (audience): "taskprinter-mcp"

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASKPRINTER_AUTH_ENABLED` | `true` | Enable/disable authentication |
| `TASKPRINTER_JWT_SECRET` | auto-generated | Secret key for JWT signing |

### Secret Key Management

The JWT secret key is managed automatically:

1. **Environment Variable**: If `TASKPRINTER_JWT_SECRET` is set, it's used
2. **Local File**: Stored in `~/.taskprinter/jwt_secret` with secure permissions
3. **Auto-Generation**: If neither exists, a new secret is generated and saved

The secret file is created with `600` permissions (readable only by the owner).

### Token Expiration

Tokens expire after 30 days by default. To generate tokens with custom expiration:

```python
from task_printer.mcp.auth import SimpleJWTAuth

auth = SimpleJWTAuth(token_expiry_days=7)  # 7 days
token = auth.generate_token("my-user")
```

## Disabling Authentication

To run the MCP server without authentication (not recommended for production):

```bash
export TASKPRINTER_AUTH_ENABLED=false
python mcp_server.py
```

The server will log:
```
🔓 JWT Authentication: DISABLED (set TASKPRINTER_AUTH_ENABLED=true to enable)
```

## Security Considerations

### For Single-User Scenarios

This authentication system is designed for single-user environments where:
- You control both the token generation and MCP server
- The server runs on localhost or a trusted network
- You don't need complex user management

### Production Recommendations

For production deployments with multiple users, consider:
- Using asymmetric JWT keys (RS256 instead of HS256)
- Implementing proper user management
- Using external identity providers
- Adding rate limiting and monitoring
- Using HTTPS for all connections

## Troubleshooting

### Token Validation Errors

If you see authentication errors:

1. **Check token expiration**: Generate a new token if the old one expired
2. **Verify secret consistency**: Ensure the same secret is used for generation and validation
3. **Check token format**: Ensure the token is properly included in the Authorization header

### Secret Key Issues

If you have problems with secret keys:

1. **Check file permissions**: The secret file should be readable only by you
2. **Verify environment variables**: Check if `TASKPRINTER_JWT_SECRET` is set correctly
3. **Regenerate secret**: Delete `~/.taskprinter/jwt_secret` to generate a new one

### Common Error Messages

- `"JWT token has expired"`: Generate a new token
- `"Invalid JWT token"`: Check token format and secret key consistency
- `"FastMCP JWT provider not available"`: Install FastMCP with `pip install fastmcp`

## CLI Reference

### Generate Token

```bash
python scripts/generate_token.py [username]
```

- `username` (optional): User identifier for the token (default: "taskprinter-user")

### Examples

```bash
# Generate token with default username
uv run python scripts/generate_token.py

# Generate token with custom username
uv run python scripts/generate_token.py alice

# Save token to environment variable (macOS/Linux)
export TASKPRINTER_AUTH_TOKEN=$(uv run python scripts/generate_token.py | grep "Token:" | cut -d' ' -f2)
```

## Integration Examples

### Python MCP Client

```python
import httpx

token = "your-jwt-token-here"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json"
}

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", 
            "id": 1, 
            "method": "initialize", 
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "my-client", "version": "1.0.0"}
            }
        }
    )
    print(response.text)
```

### curl Example

```bash
# Initialize MCP session
curl -H "Authorization: Bearer your-jwt-token-here" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/mcp \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}'
```

## Testing Authentication

### Test Without Token (Should Fail)
```bash
curl -s -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/mcp \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}'

# Expected response:
# {"error": "invalid_token", "error_description": "Authentication required"}
```

### Test With Valid Token (Should Succeed)
```bash
TOKEN=$(uv run python scripts/generate_token.py | grep "Token:" | cut -d' ' -f2)
curl -s -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/mcp \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}'

# Expected response:
# event: message
# data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",...}}
```

This authentication system provides a good balance of security and simplicity for single-user MCP server deployments.
