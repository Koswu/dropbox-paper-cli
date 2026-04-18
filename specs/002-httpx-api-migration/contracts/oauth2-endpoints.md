# Contract: OAuth2 Endpoints

**Feature**: 002-httpx-api-migration
**Date**: 2025-07-15

OAuth2 flows use standard HTTP endpoints. These replace the SDK's `DropboxOAuth2FlowNoRedirect` class.

---

## Authorization URL (Browser Redirect)

Not an HTTP API call — this is a URL the user opens in their browser.

### PKCE Flow

```
GET https://www.dropbox.com/oauth2/authorize
    ?client_id={app_key}
    &response_type=code
    &code_challenge={code_challenge}
    &code_challenge_method=S256
    &token_access_type=offline
```

**Parameters**:
| Parameter | Value | Notes |
|-----------|-------|-------|
| `client_id` | App key | From config or env var |
| `response_type` | `code` | Always |
| `code_challenge` | `base64url(sha256(code_verifier))` | PKCE challenge |
| `code_challenge_method` | `S256` | SHA-256 |
| `token_access_type` | `offline` | Grants refresh token |

### Authorization Code Flow

```
GET https://www.dropbox.com/oauth2/authorize
    ?client_id={app_key}
    &response_type=code
    &token_access_type=offline
```

No `code_challenge` parameters — uses `client_secret` at token exchange instead.

---

## Token Exchange

```
POST https://api.dropboxapi.com/oauth2/token
Content-Type: application/x-www-form-urlencoded
```

### PKCE Flow

**Request Body** (form-encoded):
```
grant_type=authorization_code
&code={authorization_code}
&client_id={app_key}
&code_verifier={code_verifier}
```

### Authorization Code Flow

**Request Body** (form-encoded):
```
grant_type=authorization_code
&code={authorization_code}
&client_id={app_key}
&client_secret={app_secret}
```

### Response (200 OK)

```json
{
    "access_token": "sl.B...",
    "token_type": "bearer",
    "expires_in": 14400,
    "refresh_token": "rt.A...",
    "scope": "account_info.read files.content.read files.content.write files.metadata.read files.metadata.write sharing.read sharing.write",
    "uid": "12345",
    "account_id": "dbid:AAB..."
}
```

**Field Mapping to AuthToken**:
| Response Field | AuthToken Field | Transform |
|---------------|----------------|-----------|
| `access_token` | `access_token` | Direct |
| `refresh_token` | `refresh_token` | Direct |
| `expires_in` | `expires_at` | `time.time() + expires_in` |
| `account_id` | `account_id` | Direct |
| `uid` | `uid` | Direct |
| `token_type` | `token_type` | Direct |

**Note**: `root_namespace_id` and `home_namespace_id` are NOT in the token response. They come from `users/get_current_account` (see RPC endpoints contract). They are fetched after token exchange and persisted into the AuthToken.

---

## Token Refresh

```
POST https://api.dropboxapi.com/oauth2/token
Content-Type: application/x-www-form-urlencoded
```

**Request Body** (form-encoded):
```
grant_type=refresh_token
&refresh_token={refresh_token}
&client_id={app_key}
```

### Response (200 OK)

```json
{
    "access_token": "sl.B...",
    "token_type": "bearer",
    "expires_in": 14400
}
```

**Note**: Token refresh does NOT return a new `refresh_token`. The original refresh token remains valid. Only `access_token` and `expires_in` are updated.

**Field Mapping**:
| Response Field | AuthToken Field | Transform |
|---------------|----------------|-----------|
| `access_token` | `access_token` | Replace |
| `expires_in` | `expires_at` | `time.time() + expires_in` |
| (unchanged) | `refresh_token` | Keep existing |
| (unchanged) | `account_id` | Keep existing |
| (unchanged) | `uid` | Keep existing |
| (unchanged) | `root_namespace_id` | Keep existing |
| (unchanged) | `home_namespace_id` | Keep existing |

### Error Response (400/401)

```json
{
    "error": "invalid_grant",
    "error_description": "refresh token is invalid or revoked"
}
```

**Handling**: If refresh fails with `invalid_grant`, raise `AuthenticationError` with message instructing user to re-authenticate via `paper auth login`.

---

## PKCE Implementation

Generate PKCE parameters using Python stdlib only (no external dependencies):

```python
import hashlib
import base64
import secrets

def generate_pkce_pair() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for OAuth2 PKCE."""
    # 32 bytes = 43 base64url characters (within 43-128 char spec range)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    
    # S256: SHA-256 hash of verifier, base64url-encoded
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    
    return code_verifier, code_challenge
```

---

## Timeout

All OAuth2 token endpoints use `METADATA_TIMEOUT` (connect=5s, read=5s) since they exchange small JSON payloads only.
