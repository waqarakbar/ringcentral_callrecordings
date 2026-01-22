# NICE inContact CXone API Authentication

Python script for authenticating with the NICE inContact CXone API.

## Features

- ✅ OAuth 2.0 password grant authentication
- ✅ Automatic token expiry management
- ✅ Secure credential storage using environment variables
- ✅ Comprehensive error handling
- ✅ Reusable class-based design
- ✅ Type hints for better IDE support

## Installation

1. **Install dependencies:**
```bash
run uv sync --locked
```

2. **Set up credentials:**
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your actual credentials
nano .env  # or use your preferred editor
```

3. **Update the `.env` file with your credentials:**
```env
CXONE_USERNAME=your_actual_username
CXONE_PASSWORD=your_actual_password
CXONE_CLIENT_ID=your_actual_client_id
CXONE_CLIENT_SECRET=your_actual_client_secret
```

## Usage

### Standalone Script

Run the authentication script directly to test your credentials:

```bash
python auth.py
```

### Using in Your Code

Import and use the `CXoneAuthenticator` class in your own scripts:

```python
from auth import CXoneAuthenticator
import requests

# Create authenticator (credentials loaded from .env)
auth = CXoneAuthenticator()

# Get access token
token = auth.get_access_token()

# Use the token in API requests
headers = auth.get_auth_header()

# Example API call
response = requests.get(
    "https://api.niceincontact.com/some-endpoint",
    headers=headers
)
```

### Manual Credential Passing

You can also pass credentials directly (not recommended for production):

```python
auth = CXoneAuthenticator(
    username="your_username",
    password="your_password",
    client_id="your_client_id",
    client_secret="your_client_secret"
)
```

## API Response

The authentication returns the following response:

```json
{
    "access_token": "eyJhbGci...",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "eyJhbGci...",
    "id_token": "eyJhbGci...",
    "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"
}
```

## Class Methods

### `CXoneAuthenticator`

- **`__init__(username, password, client_id, client_secret)`** - Initialize with credentials
- **`authenticate()`** - Perform authentication and get tokens
- **`get_access_token()`** - Get a valid access token (auto-refreshes if expired)
- **`is_token_expired()`** - Check if current token is expired
- **`get_auth_header()`** - Get authorization header dict for API requests

## Error Handling

The script includes comprehensive error handling:

- ❌ Missing credentials validation
- ❌ HTTP error responses
- ❌ Network timeout handling
- ❌ Invalid response parsing

## Security Notes

⚠️ **Important:**
- Never commit your `.env` file to version control
- The `.gitignore` file is configured to exclude `.env`
- Keep your credentials secure and rotate them regularly
- Use environment variables in production environments

## Troubleshooting

**"Recording not found" error (404):**
```
⚠️  Recording not found for contact ID: 507992643276
   This contact either:
   - Doesn't exist in the system
   - Doesn't have a recording
   - Recording has expired or been deleted
```
This is **not an error with the script** - it means the specific contact ID you're trying to fetch doesn't have an available recording. Make sure you're using a contact ID that:
- Exists in your CXone system
- Has a completed call with recording enabled
- The recording hasn't expired or been deleted

**Authentication fails:**
- Verify your credentials are correct in `.env`
- Check that your client_id and client_secret are valid
- Ensure your account has API access enabled

**Import errors:**
- Make sure you've installed all dependencies: `pip install -r requirements.txt` or use `uv`

**Token expired errors:**
- The class automatically handles token expiry and re-authentication
- If issues persist, manually call `authenticate()` again

## License

This script is provided as-is for use with NICE inContact CXone API.
