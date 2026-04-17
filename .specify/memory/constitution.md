<!--
  Sync Impact Report
  ==================
  Version change: 0.0.0 → 1.0.0 (MAJOR: initial constitution ratification)
  Modified principles: N/A (initial creation)
  Added sections:
    - Core Principles (7 principles: CLI-First, SDK Wrapper + Extensions,
      Local Metadata Cache, Agent-Friendly, Auth Flexibility,
      Test-First, Simplicity)
    - Technical Constraints (tech stack, target platform, boundaries)
    - Development Workflow (TDD cycle, commit discipline, quality gates)
    - Governance (amendment procedure, versioning, compliance)
  Removed sections: N/A (initial creation)
  Templates status:
    - .specify/templates/plan-template.md        ✅ compatible (generic
      Constitution Check gate aligns with 7 principles)
    - .specify/templates/spec-template.md         ✅ compatible (user story
      structure supports TDD and CLI-First validation)
    - .specify/templates/tasks-template.md        ✅ compatible (TDD-first
      task ordering aligns with Principle VI)
  Follow-up TODOs: None
-->

# dropbox-paper-cli Constitution

## Core Principles

### I. CLI-First

Every feature MUST be exposed as a Typer CLI command. The tool follows a
strict text-based I/O protocol:

- Arguments and stdin are the only input channels.
- Normal output goes to stdout; errors and diagnostics go to stderr.
- Every command MUST support both human-readable (default) and JSON
  (`--json` flag) output formats.
- Exit codes MUST be meaningful: 0 for success, non-zero for errors
  with distinct codes for different failure categories.

**Rationale**: CLI-first design ensures composability with shell
pipelines, cron jobs, and AI agent tool-calling workflows.

### II. SDK Wrapper + Extensions

The primary goal is to wrap **all** Dropbox Paper SDK capabilities as
CLI commands, providing a one-to-one mapping where feasible.

- SDK wrapper commands MUST live in a dedicated layer that directly
  translates CLI arguments to SDK calls and SDK responses to CLI output.
- Extension features (e.g., local search) build **on top of** the SDK
  layer but MUST remain separate concerns with clear module boundaries.
- SDK wrapper code MUST NOT depend on extension modules; extensions MAY
  depend on the SDK layer.

**Rationale**: Clean separation allows SDK coverage to advance
independently of local-only features, and keeps the dependency graph
acyclic.

### III. Local Metadata Cache

The tool syncs the Dropbox Paper directory tree (metadata only) into a
local SQLite database to enable fast local search by file and folder
names.

- Only metadata (names, IDs, paths, timestamps) is cached locally;
  document content is NOT stored.
- The sync command MUST be idempotent and support incremental updates.
- All local search operates against the SQLite cache, never against the
  remote API for filename lookups.

**Rationale**: Dropbox's native search is slow and unreliable for
filename-based lookups. A local metadata cache provides sub-second
keyword search without API round-trips.

### IV. Agent-Friendly

This tool is designed to be operated by AI agents as well as human
users. Commands MUST produce predictable, machine-parseable output.

- JSON mode (`--json`) MUST return well-structured objects with stable
  key names across versions.
- Error responses in JSON mode MUST include an `error` key with a
  human-readable message and a `code` key with a machine-readable
  error identifier.
- Commands MUST NOT require interactive prompts during normal operation;
  all inputs are supplied via arguments, flags, or stdin.
- Help text MUST be clear enough for an LLM to determine correct usage
  from `--help` output alone.

**Rationale**: AI agents are a primary consumer. Predictable,
non-interactive output is essential for automated tool-calling
pipelines.

### V. Auth Flexibility

Authentication MUST support multiple OAuth2 flows to accommodate
different deployment contexts.

- **OAuth2 PKCE** (recommended): No backend server required; suitable
  for local CLI use and single-user setups.
- **OAuth2 Authorization Code**: Supported for environments where a
  backend callback server is available.
- Tokens MUST be persisted securely in local storage (e.g., OS keyring
  or encrypted file) and refreshed automatically when expired.
- The auth subsystem MUST be modular so additional flows can be added
  without modifying existing command code.

**Rationale**: Different users and deployment environments have
different auth constraints. Supporting both PKCE and authorization
code flow covers the common cases without backend dependencies.

### VI. Test-First (NON-NEGOTIABLE)

All feature code MUST be developed using Test-Driven Development.

- Tests MUST be written **before** implementation code.
- The Red-Green-Refactor cycle is strictly enforced:
  1. Write a failing test that defines the desired behavior.
  2. Write the minimal implementation to make the test pass.
  3. Refactor while keeping all tests green.
- pytest is the mandated test framework.
- Test files MUST mirror source structure under `tests/`.
- Mocking of Dropbox SDK calls is required for unit tests; integration
  tests against the live API are a separate, opt-in test suite.

**Rationale**: TDD prevents regressions, documents behavior as
executable specifications, and enforces small incremental changes.

### VII. Simplicity

Start simple. Follow YAGNI (You Aren't Gonna Need It) principles.

- Do NOT build features that are not explicitly required by the current
  specification.
- Full-text content search is explicitly out of scope for v1; this
  version focuses on metadata sync and filename keyword search.
- Prefer standard library solutions over third-party packages when the
  capability difference is marginal.
- Each module MUST have a single, clear responsibility. If a module
  description requires "and", it should likely be split.

**Rationale**: Premature complexity is the primary risk for a CLI tool.
Keeping scope tight ensures the tool ships and remains maintainable.

## Technical Constraints

- **Language**: Python 3.12+ (required; no support for earlier versions)
- **Package Manager**: uv (for dependency resolution and virtual
  environment management)
- **CLI Framework**: Typer (type-hint style commands built on Click)
- **Local Storage**: SQLite (via Python's built-in `sqlite3` module for
  metadata cache)
- **Output Formats**: JSON (structured, `--json` flag) and
  human-readable (default)
- **Target Users**: CLI-savvy developers and AI agents that need to
  search, read, and manage Dropbox Paper documents programmatically
- **Platform**: Linux and macOS (primary); Windows support is
  best-effort and not a blocking requirement

## Development Workflow

### TDD Cycle

1. Write test(s) for the next behavior increment.
2. Run tests — confirm they **fail** (Red).
3. Implement the minimal code to pass (Green).
4. Refactor for clarity and design, keeping tests green (Refactor).
5. Commit.

### Commit Discipline

- Each commit MUST represent a single logical change.
- Commit messages MUST follow Conventional Commits format
  (e.g., `feat:`, `fix:`, `test:`, `docs:`, `refactor:`).

### Quality Gates

- All tests MUST pass before any merge to the main branch.
- New CLI commands MUST include corresponding test coverage.
- Linting (ruff) and type checking (mypy or pyright) MUST pass
  without errors on all committed code.

## Governance

This constitution is the highest-authority document for the
dropbox-paper-cli project. All design decisions, code reviews, and
feature specifications MUST comply with the principles defined above.

### Amendment Procedure

1. Propose the change with a rationale in a pull request modifying this
   file.
2. Document the version bump type (MAJOR / MINOR / PATCH) and
   justification.
3. Update the Sync Impact Report at the top of this file.
4. Ensure all dependent templates and documentation are updated to
   reflect the change.

### Versioning Policy

- **MAJOR**: Backward-incompatible principle removals or redefinitions.
- **MINOR**: New principle or section added, or existing guidance
  materially expanded.
- **PATCH**: Clarifications, wording improvements, typo fixes.

### Compliance Review

- Every pull request MUST be checked against this constitution's
  principles before merge.
- Complexity beyond what these principles allow MUST be justified in
  the PR description with a reference to the specific principle being
  stretched and why.

**Version**: 1.0.0 | **Ratified**: 2026-04-17 | **Last Amended**: 2026-04-17
