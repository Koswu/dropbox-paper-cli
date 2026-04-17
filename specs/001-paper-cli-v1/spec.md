# Feature Specification: Dropbox Paper CLI v1.0

**Feature Branch**: `001-paper-cli-v1`  
**Created**: 2025-07-18  
**Status**: Complete  
**Input**: User description: "Initial v1.0 release of dropbox-paper-cli — a Python CLI tool wrapping Dropbox Paper SDK operations with local search capabilities"

## Clarifications

### Session 2026-04-17

- Q: What code quality tooling should be specified for linting, formatting, and type checking? → A: ruff (lint + format) + ty (type check)
- Q: What format should the read command output for Paper document content? → A: Markdown (default); no HTML export in v1
- Q: How should CLI commands be organized — flat namespace or grouped subcommands? → A: Grouped subcommands by domain (e.g., `paper auth login`, `paper files list`, `paper cache sync`)
- Q: Should the CLI support diagnostic/debug output for troubleshooting? → A: `--verbose` flag emitting diagnostic output to stderr
- Q: Should the CLI auto-retry transient failures (network errors, rate limits) or fail immediately? → A: Auto-retry up to 3 times with exponential backoff for transient errors

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authenticate and Connect (Priority: P1)

A user installs the CLI and needs to connect it to their Dropbox account before any other operation is possible. The user runs an authentication command, is guided through an OAuth2 flow in their browser, and the CLI securely stores the resulting token for all future sessions. On subsequent runs, the CLI automatically uses the stored token and silently refreshes it when it expires.

**Why this priority**: Authentication is the gateway to every other feature. Without it, no SDK commands work. This must be rock-solid and seamless.

**Independent Test**: Can be fully tested by running the auth command, completing the OAuth2 flow, and verifying the token is stored. A subsequent command (e.g., listing the root folder) confirms the token works without re-authentication.

**Acceptance Scenarios**:

1. **Given** a user with no stored credentials, **When** they run the auth command, **Then** the CLI opens a browser for OAuth2 authorization, receives the callback, stores the token securely, and confirms success on stdout.
2. **Given** a user with a valid stored token, **When** they run any SDK command, **Then** the CLI uses the stored token without prompting for re-authentication.
3. **Given** a user with an expired token, **When** they run any SDK command, **Then** the CLI automatically refreshes the token and completes the command without user intervention.
4. **Given** a user who wants to switch accounts or re-authorize, **When** they run the auth command again, **Then** the CLI replaces the stored token with the new one.
5. **Given** a user whose refresh token is revoked or invalid, **When** they run any SDK command, **Then** the CLI outputs a clear error to stderr instructing the user to re-authenticate, and exits with a non-zero code.

---

### User Story 2 - Browse and Inspect Files and Folders (Priority: P1)

A developer wants to explore their Dropbox Paper directory structure from the terminal. They list files and folders at any path, inspect metadata for a specific item, and retrieve sharing links — all without opening a browser.

**Why this priority**: Browsing is the fundamental read operation. Users need to see what exists before they can move, copy, delete, or read content.

**Independent Test**: Can be tested by listing the root folder, listing a subfolder, and getting metadata for a specific file. Verify output in both human-readable and JSON formats.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they run the list command for the root path, **Then** the CLI displays all top-level files and folders with names, types, and modification dates.
2. **Given** an authenticated user, **When** they run the list command for a specific folder path, **Then** the CLI displays the contents of that folder.
3. **Given** an authenticated user, **When** they run the metadata command for a specific file or folder (by path or ID), **Then** the CLI displays detailed metadata (name, type, size, modification date, path, ID).
4. **Given** an authenticated user, **When** they run the sharing-link command for a file, **Then** the CLI returns the sharing URL for that file.
5. **Given** an authenticated user who supplies a Dropbox Paper URL instead of a file ID, **When** they run any file command, **Then** the CLI extracts the file ID from the URL and performs the requested operation.
6. **Given** an authenticated user, **When** they request output with the `--json` flag, **Then** the CLI returns structured JSON to stdout.
7. **Given** an authenticated user, **When** they reference a path or ID that does not exist, **Then** the CLI outputs an error to stderr and exits with a non-zero code.

---

### User Story 3 - Organize Files and Folders (Priority: P1)

A user needs to reorganize their Dropbox Paper directory structure from the CLI. They create new folders, move files between folders, copy files, and delete items they no longer need. Moving files is particularly important because the Dropbox web UI makes this operation painful and slow.

**Why this priority**: File organization (especially move) is the primary pain point the user identified. This directly addresses the core motivation for building the tool.

**Independent Test**: Can be tested by creating a folder, moving a file into it, copying a file, and deleting an item. Verify each operation produces correct output and the remote state reflects the change.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they run the create-folder command with a path, **Then** a new folder is created at the specified location and the CLI confirms with the new folder's metadata.
2. **Given** an authenticated user, **When** they run the move command with a source and destination, **Then** the file or folder is moved and the CLI confirms the new location.
3. **Given** an authenticated user who provides a Dropbox Paper URL as the source for a move command, **When** the command executes, **Then** the CLI extracts the file ID from the URL and moves the item successfully.
4. **Given** an authenticated user, **When** they run the copy command with a source and destination, **Then** the file or folder is copied and the CLI confirms the new copy's metadata.
5. **Given** an authenticated user, **When** they run the delete command for a file or folder, **Then** the item is removed and the CLI confirms deletion.
6. **Given** an authenticated user, **When** they attempt to move or copy to an invalid destination, **Then** the CLI outputs an error to stderr and exits with a non-zero code.
7. **Given** an authenticated user, **When** they attempt to delete a non-existent item, **Then** the CLI outputs an error to stderr and exits with a non-zero code.

---

### User Story 4 - Read Paper Document Content (Priority: P1)

An AI agent (or developer) needs to read the content of a Dropbox Paper document programmatically. They run a command with a file ID (or URL), and the CLI outputs the document content to stdout. This enables AI agents to ingest Paper documents into knowledge bases or processing pipelines.

**Why this priority**: Reading document content is the core value proposition for AI agent integration — a primary target user group. Without this, the tool is just a file manager.

**Independent Test**: Can be tested by reading a known Paper document and verifying the output contains the document content. Test both human-readable and JSON output modes.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they run the read command with a valid file ID, **Then** the CLI outputs the document content as Markdown to stdout.
2. **Given** an authenticated user, **When** they run the read command with a Dropbox Paper URL, **Then** the CLI extracts the file ID and outputs the document content as Markdown.
3. **Given** an authenticated user, **When** they run the read command with the `--json` flag, **Then** the output includes the document content wrapped in a structured JSON object with metadata.
4. **Given** an authenticated user, **When** they attempt to read a non-existent or inaccessible file, **Then** the CLI outputs an error to stderr and exits with a non-zero code.
5. **Given** an authenticated user, **When** they attempt to read a folder (not a file), **Then** the CLI outputs a clear error indicating the target is not a readable document.

---

### User Story 5 - Sync and Search Local Metadata Cache (Priority: P2)

A user has hundreds of Paper documents and wants to find specific ones by name without waiting for slow API search responses. They first sync the Dropbox directory tree metadata to a local cache, then search file and folder names instantly by keyword. Subsequent syncs are incremental and only fetch changes.

**Why this priority**: Local search is a key differentiator of the tool over the raw SDK, but it depends on the SDK wrapper layer being functional first.

**Independent Test**: Can be tested by running a sync command, verifying the local cache is populated, then running a search query and verifying sub-second results that match known file names.

**Acceptance Scenarios**:

1. **Given** an authenticated user with no local cache, **When** they run the sync command, **Then** the CLI downloads the full directory tree metadata and stores it locally, reporting the number of items synced.
2. **Given** an authenticated user with an existing local cache, **When** they run the sync command again, **Then** the CLI performs an incremental sync, fetching only changes since the last sync and reporting what was added, updated, or removed.
3. **Given** a user with a populated local cache, **When** they run the search command with a keyword, **Then** the CLI returns matching file and folder names with their paths in sub-second time without making any API calls.
4. **Given** a user with a populated local cache, **When** they search with the `--json` flag, **Then** the results are returned as a JSON array of objects containing name, path, ID, and type.
5. **Given** a user with a populated local cache, **When** they search for a keyword that matches nothing, **Then** the CLI outputs an empty result set (empty list in JSON mode, a "no results" message in human-readable mode).
6. **Given** a user whose sync is interrupted, **When** they run sync again, **Then** the CLI resumes or restarts gracefully without corrupting the local cache.

---

### User Story 6 - Get Shared Folder Information (Priority: P3)

A user wants to inspect the sharing settings and membership of shared folders. They run a command and see who has access and what permissions are set.

**Why this priority**: Shared folder info is useful for auditing and understanding access, but it's a secondary need compared to core browse/organize/read workflows.

**Independent Test**: Can be tested by querying sharing info for a known shared folder and verifying the output contains members and permission levels.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they run the shared-folder-info command for a shared folder, **Then** the CLI displays folder members, their roles, and sharing settings.
2. **Given** an authenticated user, **When** they query a non-shared folder, **Then** the CLI indicates the folder is not shared.
3. **Given** an authenticated user, **When** they run the command with `--json`, **Then** the output is structured JSON with sharing metadata.

---

### Edge Cases

- What happens when the user's network connection drops mid-operation? → CLI retries up to 3 times with exponential backoff; if all retries fail, outputs a connection error to stderr with a retry-friendly message and a non-zero exit code.
- What happens when the Dropbox API rate limit is exceeded? → CLI retries up to 3 times with exponential backoff (respecting retry-after header); if all retries fail, outputs a rate-limit error to stderr with the retry-after time and exits with a distinct non-zero code.
- What happens when a file path contains special characters (spaces, Unicode, emoji)? → CLI handles these correctly, quoting or escaping as needed for shell compatibility.
- What happens when the local SQLite cache file is corrupted or missing? → The sync command recreates the cache from scratch; search commands report that a sync is needed.
- What happens when the user provides both a URL and a file ID flag? → CLI uses the explicitly provided file ID and ignores the URL, or outputs a clear conflict error.
- What happens when a move or copy destination already exists? → CLI reports a conflict error to stderr with a descriptive message about the existing item.
- What happens when the user attempts an operation on a file they don't have permission for? → CLI surfaces the Dropbox permission error clearly on stderr.

## Requirements *(mandatory)*

### Functional Requirements

**CLI Structure**

- **FR-001A**: Commands MUST be organized into grouped subcommands by domain using Typer's subcommand support: `auth` (authentication), `files` (browse, organize, read), `cache` (sync, search), `sharing` (shared folder info).
- **FR-001B**: Top-level `--help` MUST list all command groups with short descriptions. Each group's `--help` MUST list its subcommands.

**Authentication**

- **FR-001**: System MUST support OAuth2 PKCE flow for authentication without requiring a backend server.
- **FR-002**: System MUST support OAuth2 Authorization Code flow as an alternative authentication method.
- **FR-003**: System MUST persist authentication tokens securely in local storage.
- **FR-004**: System MUST automatically refresh expired access tokens using the stored refresh token without user intervention.
- **FR-005**: System MUST provide a command to initiate authentication and a command to revoke/clear stored credentials.

**SDK Wrapper — Browsing**

- **FR-010**: System MUST provide a command to list files and folders at a given Dropbox path.
- **FR-011**: System MUST provide a command to get detailed metadata for a specific file or folder.
- **FR-012**: System MUST provide a command to retrieve the sharing link for a file.

**SDK Wrapper — Organizing**

- **FR-020**: System MUST provide a command to create a new folder at a specified path.
- **FR-021**: System MUST provide a command to move a file or folder from one location to another.
- **FR-022**: System MUST provide a command to copy a file or folder to a new location.
- **FR-023**: System MUST provide a command to delete a file or folder.

**SDK Wrapper — Content**

- **FR-030**: System MUST provide a command to read and output the content of a Paper document in Markdown format.
- **FR-031**: The read command MUST export Paper documents as Markdown by default. HTML export is out of scope for v1.

**SDK Wrapper — Sharing**

- **FR-040**: System MUST provide a command to get shared folder information including members and permissions.

**URL Parsing**

- **FR-050**: System MUST accept Dropbox Paper URLs wherever file or folder IDs are accepted.
- **FR-051**: System MUST extract the file ID from Dropbox Paper URLs in the format `https://www.dropbox.com/scl/fi/<file_id>/<name>?rlkey=...&dl=...`.
- **FR-052**: System MUST report a clear error when a provided URL cannot be parsed into a valid file ID.

**Local Metadata Cache & Search**

- **FR-060**: System MUST provide a command to sync the Dropbox Paper directory tree metadata to a local SQLite database.
- **FR-061**: System MUST support incremental sync, fetching only changes since the last sync operation.
- **FR-062**: System MUST provide a command to search file and folder names by keyword against the local cache.
- **FR-063**: Local search MUST NOT make any Dropbox API calls.
- **FR-064**: System MUST handle a corrupted or missing local cache gracefully by recreating it on the next sync.

**Output & Error Handling**

- **FR-070**: Every command MUST support a `--json` flag that produces structured JSON output to stdout.
- **FR-071**: Default output for every command MUST be human-readable formatted text.
- **FR-072**: All error messages MUST be written to stderr.
- **FR-073**: Every command MUST exit with code 0 on success and a non-zero code on failure, with distinct codes for different failure categories.
- **FR-074**: JSON-mode error output MUST include an `error` key with a human-readable message and a `code` key with a machine-readable identifier.
- **FR-075**: Commands MUST NOT require interactive prompts during normal operation; all inputs are supplied via arguments, flags, or stdin.
- **FR-076**: Every command MUST support a `--verbose` flag that emits diagnostic information (HTTP calls, token refresh attempts, cache operations) to stderr, keeping stdout reserved for data output.

**Retry & Resilience**

- **FR-077**: Commands that make Dropbox API calls MUST automatically retry transient failures (network errors, HTTP 429 rate limits, HTTP 5xx server errors) up to 3 times with exponential backoff.
- **FR-078**: Retry attempts MUST be logged to stderr when `--verbose` is enabled.
- **FR-079**: If all retries are exhausted, the command MUST exit with a non-zero code and output an actionable error message including the retry-after hint when available from the API response.

### Non-Functional Requirements

**Development Quality Gates**

- **NFR-001**: All code MUST pass ruff linting with zero errors before merge.
- **NFR-002**: All code MUST pass ruff formatting checks (consistent style enforcement) before merge.
- **NFR-003**: All code MUST pass ty type checking with zero errors before merge.
- **NFR-004**: All tests MUST pass (pytest) before merge.

### Key Entities

- **DropboxItem**: Represents a file or folder in Dropbox. Key attributes: ID, name, path, type (file/folder), modification timestamp, size (files only).
- **PaperDocument**: A specialized DropboxItem representing a Dropbox Paper document. Has all DropboxItem attributes plus the ability to retrieve content.
- **SharingInfo**: Represents sharing metadata for a folder. Key attributes: shared folder ID, members (with roles/permissions), sharing policy.
- **AuthToken**: Represents the user's authentication state. Key attributes: access token, refresh token, expiration timestamp, account identifier.
- **CachedMetadata**: Represents a locally-stored metadata entry in the SQLite cache. Key attributes: Dropbox ID, name, path, type, parent folder ID, last synced timestamp, remote modification timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can authenticate and begin using the CLI within 2 minutes of first install.
- **SC-002**: All file organization operations (move, copy, create folder, delete) complete and return confirmation within 10 seconds for a single item under normal network conditions.
- **SC-003**: Users can read the full content of a Paper document in a single command invocation.
- **SC-004**: Local keyword search returns results in under 1 second for a cache containing up to 10,000 items.
- **SC-005**: Incremental sync completes in under 30 seconds when fewer than 100 items have changed since the last sync.
- **SC-006**: Every command produces valid, parseable JSON when the `--json` flag is used.
- **SC-007**: An AI agent can discover correct command usage from `--help` output alone, without external documentation.
- **SC-008**: All error conditions produce meaningful messages on stderr with non-zero exit codes, enabling automated error handling in scripts.
- **SC-009**: Users can use Dropbox Paper URLs interchangeably with file IDs in all file-related commands.
- **SC-010**: A full initial metadata sync of a directory tree with up to 10,000 items completes within 5 minutes.

## Assumptions

- Users have Python 3.12+ and uv installed or can install them before using this tool.
- Users have a Dropbox account with access to Dropbox Paper documents.
- Users have a working internet connection for all SDK wrapper commands; only local search operates offline.
- The Dropbox Python SDK (`dropbox` package) provides stable, documented methods for all operations listed in the requirements (list, metadata, move, copy, delete, read content, sharing info).
- The Dropbox API rate limits are sufficient for normal single-user CLI usage patterns (individual commands, not bulk automation).
- Token storage uses the filesystem (e.g., a config directory like `~/.dropbox-paper-cli/`) with appropriate file permissions; OS keyring integration is a potential future enhancement but not required for v1.
- The provided app credentials (app key: `REDACTED_APP_KEY`) are valid and have the necessary permissions for all operations.
- This is a production Dropbox environment — the tool MUST NOT modify existing content during development/testing unless explicitly instructed by the user.
- The Dropbox Paper URL format (`https://www.dropbox.com/scl/fi/<id>/<name>?rlkey=...`) is the standard format; other URL variants may exist but only this format is guaranteed supported in v1.
- Linux and macOS are the primary platforms; Windows compatibility is best-effort.
- Full-text content search, document content caching, batch operations, and real-time sync / watch mode are explicitly out of scope for v1.
