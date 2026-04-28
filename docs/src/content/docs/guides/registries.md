---
title: "Registries"
description: "Declare REST-based APM registries in apm.yml and consume packages from them alongside Git-hosted dependencies."
sidebar:
  order: 6
---

A **registry** is a REST-based source for APM packages. Any service that implements the [Registry HTTP API](../../reference/registry-http-api/) qualifies. Registries sit alongside the existing Git resolver: declare a `registries:` block in `apm.yml` and individual dependencies route to the registry by name. Registries are strictly additive. A project without a `registries:` block sees zero behavior change — every existing dependency form continues to resolve through Git exactly as before.

::::caution[Experimental]
Package registries are currently behind an experimental flag. Enable them before adding `registries:` or registry-scoped dependencies:

```bash
apm experimental enable package-registry
```
::::

## Declare a registry

Add a top-level `registries:` block to `apm.yml`:

```yaml
registries:
  jf-skills:
    url: https://registry.example.com/apm/jf-skills
  default: jf-skills
```

Each entry is a name mapped to a base URL. The optional `default:` key names one of the configured entries; when set, plain string-shorthand APM dependencies route through it (see [Default routing](#default-routing) below). Registry URLs MUST start with `https://` (or `http://` for local development).

The registry name is used both for `@<name>` scoping and for env-var auth lookup. Use lowercase letters, digits, `-`, and `.`.

## Reference a registry-sourced dependency

There are three ways to point a dependency at a registry. Pick the one that matches the shape of the dep.

### 1. String shorthand routed through the default

When `registries.default` is set, plain `owner/repo` shorthand entries route through that registry — the same syntax already used for GitHub dependencies, but now resolved over HTTP:

```yaml
registries:
  jf-skills:
    url: https://registry.example.com/apm/jf-skills
  default: jf-skills

dependencies:
  apm:
    - acme/foo#^1.2.3        # resolved via jf-skills
    - acme/bar#~2.0.0        # resolved via jf-skills
```

Routing is unconditional: every still-unrouted shorthand entry is sent through the default registry. Object-form entries (`- git:`, `- path:`, `- registry:`) and the explicit `@<name>` shorthand are left alone.

### 2. Named-scope shorthand

Append `@<registry-name>` to scope a single dependency to a specific registry, regardless of whether a default is set:

```yaml
dependencies:
  apm:
    - acme/foo@jf-skills#^1.2.3
    - acme/bar@public-mirror#1.4.0
```

Use this when the project has multiple registries and needs per-dep routing.

### 3. Object form (virtual packages)

For registry-sourced **virtual packages** — a single file or sub-path inside a published package — use the object form. Shorthand can't express the four independent fields (id, registry, sub-path, version) cleanly:

```yaml
dependencies:
  apm:
    - registry: jf-skills
      id: acme/prompt-pack
      path: prompts/review.prompt.md
      version: 1.4.0
```

| Field | Required | Description |
|---|---|---|
| `registry` | yes | Name from the `registries:` block. |
| `id` | yes | Package identity at the registry, in `owner/repo` form. |
| `path` | yes | Virtual sub-path inside the published package. |
| `version` | yes | Semver version or range. |
| `alias` | no | Local alias (controls install directory name). |

Whole-package registry deps SHOULD use shorthand or `@<name>` form — object form is reserved for virtuals.

## Strict semver requirement

Every registry-routed entry MUST specify a semver version or range. Branch refs and commit SHAs are rejected at parse time:

| Allowed | Rejected |
|---|---|
| `1.0.0`, `1.4.2` | `main`, `develop` |
| `^1.0.0`, `^1.2.3` | `abc1234` (commit SHA) |
| `~1.2.3`, `>=1.2.0` | `latest` |
| `1.2.x`, `>=1.2.0 <2.0.0` | unset (no `#<ref>`) |

Registry ranges use the same full-version semver grammar as marketplace builds:
write all three version components (`major.minor.patch`) and combine multiple
constraints with spaces, for example `>=1.2.0 <2.0.0`.

The error message points at the unchanged Git resolver as the remediation. To keep a branch or SHA pin, use the `- git:` object form for that entry:

```yaml
dependencies:
  apm:
    - acme/foo#^1.2.3                        # registry, semver-pinned
    - git: https://github.com/acme/bar.git   # git, branch-pinned
      ref: main
```

This split is intentional: registry-routed deps are byte-for-byte reproducible via `resolved_hash`; Git-routed deps are SHA-reproducible via `resolved_commit`. Each resolver enforces what it can guarantee.

## Default routing

When `registries.default` is set, the routing rules are:

| Entry form | Routed to |
|---|---|
| `owner/repo#<semver>` | Default registry |
| `owner/repo@<name>#<semver>` | Registry `<name>` |
| `- git:` object form | Git (unchanged) |
| `- path:` object form | Local filesystem (unchanged) |
| `- registry:` object form | Named registry (virtual package) |
| Virtual shorthand (`owner/repo/sub/path`) | Git (unchanged) — virtuals MUST use object form to route through a registry |

A shorthand entry without a version (`acme/foo`) is rejected when `default:` is set — registry-routed entries always require a semver.

## Authentication

APM reads credentials from environment variables named after the registry. `{NAME}` is the registry name uppercased, with `-` and `.` mapped to `_`.

| Env var | Auth method |
|---|---|
| `APM_REGISTRY_TOKEN_{NAME}` | `Authorization: Bearer <token>` |
| `APM_REGISTRY_USER_{NAME}` + `APM_REGISTRY_PASS_{NAME}` | `Authorization: Basic <base64(user:pass)>` |

Bearer wins when both forms are set. When neither is set, APM tries the request anonymously and surfaces a remediation pointing at `APM_REGISTRY_TOKEN_<NAME>` on `401`/`403`.

```bash
# Registry name "jf-skills" -> APM_REGISTRY_TOKEN_JF_SKILLS
export APM_REGISTRY_TOKEN_JF_SKILLS=eyJ...

# Or HTTP Basic for enterprise registries that issue username/password
export APM_REGISTRY_USER_JF_SKILLS=alice@example.com
export APM_REGISTRY_PASS_JF_SKILLS=...
```

The `APM_REGISTRY_*` prefix is distinct from `GITHUB_APM_PAT_*`, `PROXY_REGISTRY_*`, and `ARTIFACTORY_APM_TOKEN` — there is no collision. For the broader auth model, see [Authentication](../../getting-started/authentication/).

## What gets recorded in the lockfile

Registry-sourced dependencies add four fields to their lockfile entry: `source: registry`, `version`, `resolved_url`, and `resolved_hash` (sha256 of the archive bytes). The lockfile bumps to `lockfile_version: "2"` opportunistically — only when at least one registry dep is present. Projects that never opt into a registry keep `lockfile_version: "1"` forever, even on a newer client.

```yaml
dependencies:
  - repo_url: acme/foo
    source: registry
    version: "1.4.0"
    resolved_url: https://registry.example.com/apm/jf-skills/v1/packages/acme/foo/versions/1.4.0/download
    resolved_hash: "sha256:abc123..."
    depth: 1
    package_type: apm_package
    deployed_files:
      - .github/skills/foo/SKILL.md
```

`resolved_url` is the trust anchor for re-installs — APM re-fetches from the URL stored in the lockfile, not from the registry name, and re-verifies bytes against `resolved_hash`. See [Lockfile spec](../../reference/lockfile-spec/) for full field semantics.

## Planned features

:::note[Planned]
The following are deferred to a later milestone and not yet implemented:

- **`apm publish` command** — publishing today is done by direct `PUT` against the registry HTTP API.
- **Pre-release semver** (`-rc.1`, `-beta.2`) — accepted on publish but not advertised in version listings.
- **Yank** — marking a published version unavailable.
- **Signature verification** — cryptographic signing of registry-published packages.
:::

## See also

- [Manifest schema](../../reference/manifest-schema/) — formal grammar for the `registries:` block, `@<name>` shorthand, and `- registry:` object form.
- [Lockfile spec](../../reference/lockfile-spec/) — v2 schema and registry-specific fields.
- [Authentication](../../getting-started/authentication/) — full token-resolution chain.

If you operate a registry server, see the [Registry HTTP API](../../reference/registry-http-api/) for the full wire contract.
