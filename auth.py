"""
NICE inContact/CXone Authentication Module

This module handles authentication with the NICE inContact CXone API.
It retrieves an access token using the OAuth 2.0 password grant type.
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class CXoneAuthenticator:
    """
    Handles authentication for NICE inContact CXone API.
    
    Attributes:
        auth_url (str): The authentication endpoint URL
        username (str): API username
        password (str): API password
        client_id (str): OAuth client ID
        client_secret (str): OAuth client secret
        access_token (str): Current access token
        refresh_token (str): Current refresh token
        token_expiry (datetime): Token expiration time
    """
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None
    ):
        """
        Initialize the authenticator with credentials.
        
        Args:
            username: API username (defaults to CXONE_USERNAME env var)
            password: API password (defaults to CXONE_PASSWORD env var)
            client_id: OAuth client ID (defaults to CXONE_CLIENT_ID env var)
            client_secret: OAuth client secret (defaults to CXONE_CLIENT_SECRET env var)
        """
        self.auth_url = "https://cxone.niceincontact.com/auth/token"
        
        # Load credentials from parameters or environment variables
        self.username = username or os.getenv("CXONE_USERNAME")
        self.password = password or os.getenv("CXONE_PASSWORD")
        self.client_id = client_id or os.getenv("CXONE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CXONE_CLIENT_SECRET")
        
        # Token storage
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.id_token: Optional[str] = None
        self.token_type: str = "Bearer"
        self.token_expiry: Optional[datetime] = None
        
        # Validate credentials
        self._validate_credentials()
    
    def _validate_credentials(self) -> None:
        """
        Validate that all required credentials are present.
        
        Raises:
            ValueError: If any required credential is missing
        """
        missing = []
        if not self.username:
            missing.append("username (CXONE_USERNAME)")
        if not self.password:
            missing.append("password (CXONE_PASSWORD)")
        if not self.client_id:
            missing.append("client_id (CXONE_CLIENT_ID)")
        if not self.client_secret:
            missing.append("client_secret (CXONE_CLIENT_SECRET)")
        
        if missing:
            raise ValueError(
                f"Missing required credentials: {', '.join(missing)}\n"
                "Please provide them as parameters or set environment variables."
            )
    
    def authenticate(self) -> Dict:
        """
        Authenticate with the CXone API and retrieve access token.
        
        Returns:
            Dict containing authentication response with access_token, 
            refresh_token, expires_in, etc.
        
        Raises:
            requests.exceptions.RequestException: If the API request fails
            ValueError: If the response is invalid
        """
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            response = requests.post(
                self.auth_url,
                data=payload,
                headers=headers,
                timeout=30
            )
            
            # Raise exception for bad status codes
            response.raise_for_status()
            
            # Parse response
            auth_data = response.json()
            
            # Store tokens
            self.access_token = auth_data.get("access_token")
            self.refresh_token = auth_data.get("refresh_token")
            self.id_token = auth_data.get("id_token")
            self.token_type = auth_data.get("token_type", "Bearer")
            
            # Calculate token expiry (subtract 60 seconds as buffer)
            expires_in = auth_data.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
            
            print(f"✓ Authentication successful!")
            print(f"  Token expires at: {self.token_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            
            return auth_data
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error during authentication: {e}"
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f"\nDetails: {error_detail}"
                except:
                    error_msg += f"\nResponse: {e.response.text}"
            raise requests.exceptions.RequestException(error_msg)
        
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(
                f"Failed to authenticate: {str(e)}"
            )
        
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid authentication response: {str(e)}")
    
    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            str: Valid access token
        
        Raises:
            Exception: If unable to obtain a valid token
        """
        # Check if we need to authenticate
        if not self.access_token or self.is_token_expired():
            print("Token is expired or not available, authenticating...")
            self.authenticate()
        
        return self.access_token
    
    def is_token_expired(self) -> bool:
        """
        Check if the current access token is expired.
        
        Returns:
            bool: True if token is expired or about to expire, False otherwise
        """
        if not self.token_expiry:
            return True
        
        return datetime.now() >= self.token_expiry
    
    def get_auth_header(self) -> Dict[str, str]:
        """
        Get the authorization header for API requests.
        
        Returns:
            Dict containing the Authorization header
        """
        token = self.get_access_token()
        return {
            "Authorization": f"{self.token_type} {token}"
        }


def main():
    """
    Example usage of the CXoneAuthenticator class.
    """
    try:
        # Create authenticator instance
        auth = CXoneAuthenticator()
        
        # Authenticate and get tokens
        response = auth.authenticate()
        
        # Display token information
        print("\n" + "="*60)
        print("Authentication Response:")
        print("="*60)
        print(f"Access Token: {response['access_token'][:50]}...")
        print(f"Token Type: {response['token_type']}")
        print(f"Expires In: {response['expires_in']} seconds")
        print(f"Refresh Token: {response['refresh_token'][:50]}...")
        print("="*60)
        
        # Example: Get authorization header for API calls
        print("\nAuthorization Header for API calls:")
        print(auth.get_auth_header())
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
