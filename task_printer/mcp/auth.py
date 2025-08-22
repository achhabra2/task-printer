"""
Simple JWT-based authentication for TaskPrinter MCP server.

This module provides a simple JWT token system for single-user authentication.
It generates and validates JWT tokens using a configurable secret key.
"""

import os
import jwt
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class SimpleJWTAuth:
    """
    Simple JWT authentication for single-user MCP server.
    
    This class handles JWT token generation and provides a simple CLI
    for generating tokens that can be used with the MCP server.
    """
    
    def __init__(self, secret_key: Optional[str] = None, token_expiry_days: int = 90):
        """
        Initialize JWT authentication.
        
        Args:
            secret_key: Secret key for signing tokens. If None, reads from environment
                       or generates a random one.
            token_expiry_days: Number of days tokens remain valid (default: 30)
        """
        self.secret_key = secret_key or self._get_or_create_secret()
        self.token_expiry_days = token_expiry_days
        self.algorithm = "HS256"
        
    def _get_or_create_secret(self) -> str:
        """Get secret key from environment or create one."""
        # First try environment variable
        secret = os.environ.get("TASKPRINTER_JWT_SECRET")
        if secret:
            return secret
            
        # Try to read from local file
        secret_file = Path.home() / ".taskprinter" / "jwt_secret"
        if secret_file.exists():
            try:
                return secret_file.read_text().strip()
            except Exception as e:
                logger.warning(f"Failed to read secret from {secret_file}: {e}")
        
        # Generate new secret and save it
        import secrets
        secret = secrets.token_urlsafe(32)
        
        try:
            secret_file.parent.mkdir(exist_ok=True)
            secret_file.write_text(secret)
            secret_file.chmod(0o600)  # Make file readable only by owner
            logger.info(f"Generated new JWT secret and saved to {secret_file}")
        except Exception as e:
            logger.warning(f"Failed to save secret to {secret_file}: {e}")
            logger.info("Using in-memory secret (will not persist)")
            
        return secret
    
    def generate_token(self, user_id: str = "taskprinter-user", 
                      extra_claims: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate a JWT token.
        
        Args:
            user_id: User identifier (default: "taskprinter-user")
            extra_claims: Additional claims to include in the token
            
        Returns:
            JWT token string
        """
        now = datetime.now(timezone.utc)
        exp = now + timedelta(days=self.token_expiry_days)
        
        payload = {
            "sub": user_id,  # Subject (user ID)
            "iat": now,      # Issued at
            "exp": exp,      # Expiration
            "iss": "taskprinter-mcp",  # Issuer
            "aud": "taskprinter-mcp",  # Audience
        }
        
        if extra_claims:
            payload.update(extra_claims)
            
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload if valid, None if invalid
        """
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm],
                issuer="taskprinter-mcp",
                audience="taskprinter-mcp"
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None
    
    def get_jwks_data(self) -> Dict[str, Any]:
        """
        Get JWKS (JSON Web Key Set) data for token validation.
        
        Note: This is a simplified implementation for single-user scenarios.
        In production, you'd typically use asymmetric keys and proper JWKS.
        """
        # For symmetric keys (HMAC), we don't expose the key in JWKS
        # This is a placeholder that indicates we use HMAC
        return {
            "keys": [
                {
                    "kty": "oct",  # Octet sequence (symmetric key)
                    "alg": "HS256",
                    "use": "sig",
                    "kid": "taskprinter-key-1"
                }
            ]
        }


def create_jwt_verifier() -> Optional[object]:
    """
    Create a FastMCP JWT verifier for the authentication system.
    
    Returns:
        JWT verifier instance or None if FastMCP is not available
    """
    try:
        from fastmcp.server.auth.providers.jwt import JWTVerifier
    except ImportError:
        logger.error("FastMCP JWT provider not available")
        return None
    
    auth_system = SimpleJWTAuth()
    
    # For FastMCP JWTVerifier, we need to provide JWKS URI and issuer
    # Since we're using symmetric keys, we'll need a custom approach
    # Let's create a simple token verifier that works with our system
    
    class TaskPrinterJWTVerifier:
        """Custom JWT verifier for TaskPrinter MCP server."""
        
        def __init__(self, auth_system: SimpleJWTAuth):
            self.auth_system = auth_system
            
        async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
            """Verify JWT token."""
            return self.auth_system.verify_token(token)
            
        def get_oauth_metadata(self) -> Dict[str, Any]:
            """Get OAuth metadata for MCP discovery."""
            return {
                "issuer": "taskprinter-mcp",
                "token_endpoint": None,  # No token endpoint for this simple auth
                "jwks_uri": None,        # No public JWKS for symmetric keys
            }
    
    return TaskPrinterJWTVerifier(auth_system)


def generate_token_cli():
    """CLI function to generate a JWT token."""
    import sys
    
    auth = SimpleJWTAuth()
    
    # Check for command line arguments
    user_id = "taskprinter-user"
    if len(sys.argv) > 1:
        user_id = sys.argv[1]
    
    token = auth.generate_token(user_id)
    
    print(f"Generated JWT token for user '{user_id}':")
    print(f"Token: {token}")
    print(f"Expires: {auth.token_expiry_days} days from now")
    print()
    print("To use this token with MCP clients, set it as a Bearer token in the Authorization header:")
    print(f"Authorization: Bearer {token}")
    print()
    print("Or set the environment variable:")
    print(f"export TASKPRINTER_AUTH_TOKEN='{token}'")
    
    return token


if __name__ == "__main__":
    # Allow this module to be run directly to generate tokens
    generate_token_cli()
