# ragleap-physical: handover for the new owner

Written October 2026 for the colleague (and their Claude session) who will lead `ragleap-physical`. It is self-contained: you should not need to ask for background. It contains no secrets and must never get any (no keys, no device or server addresses, no network details).

Evidence tags: **[verified]** seen in the repo or in public project documentation; **[plan]** an intention, not built; **[unverified]** believed but not checked. Please keep using these tags in your own notes and pull requests.

## 1. The goal in one paragraph

RagLeap is an open-source platform of AI employees that work beside people. For businesses with machines, the long-term plan includes observing, and one day controlling, supported physical systems such as robots, sensors and equipment. `ragleap-physical` is a new, separate library that bridges RagLeap to open-source simulators and robot software (for example MuJoCo and ROS 2), so that contributors can build and test safely. Simulation comes first and observing comes first. Nothing controls real hardware until the evidence and the safety rules in section 7 say so. The source of this work is the "universal platform" backlog (items on devices, local gateways, large fleets, a connector framework, outcome verification and acceptance tests). None of it is built. [plan]

## 2. Your role and the boundaries

- You are the lead of `ragleap-physical`, and of this package only.
- Work inside `packages/ragleap-physical/` (code, docs, tests), its issues, and its own entries in the release setup.
- Do not edit, restart or interfere with anything that belongs to other colleagues: the other packages (`ragleap-rag`, `-graph`, `-voice`, `-phone`, `-tools`, `-agents`, `-integrations`, `-security`, `-memory` and the rest), the core app (`core/`), their containers, volumes, worktrees, branches and issues. If you need a change somewhere else, write it down for the maintainer, who decides and asks the right person. Do not ask other colleagues to change their work yourself.
- You may read everything and take ideas and references from our parts (section 4). Understand the ideas; do not copy code from one package into another. If you depend on another package, depend on its released public API only.
- Shared files are touched only in a small separate pull request that the maintainer agrees to first, and only your own lines in them: `.github/workflows/release.yml`, the feature-flag list in `tests/conftest.py`, `docker-compose.yml`, the package list in the main README.
- You may recruit and lead contributors for this package. Everyone who helps is credited by name on the website and social media, unless they opt out.
- The maintainer (Antony) does the public and production steps: merging, releases, posting issues from the project account, publishing to PyPI, npm and Maven Central, changing repository settings, spending money. Ask for an explicit go before any of those.

## 3. Decisions already made

1. **A separate library** `ragleap-physical`, MIT licence, public, pre-alpha. [plan]
2. **Simulation first, observe-only first.** Real hardware only later, behind the gates in section 6, phase 5. [plan]
3. **Packaging order: PyPI first.** Java (Maven Central) and npm come later, only after the Python interface is stable (section 8). [plan]
4. **First integration route: an MCP server.** The core already has an MCP client with an owner allowlist, so a physical bridge that offers its tools through MCP needs no change in the core at first. [plan]
5. **Every connector declares a capability level:** observe, analyse, recommend, or control. These are kept strictly separate. [plan]
6. **Honest public claims.** Until acceptance tests pass, the words are "simulation and observe-only". The README promise is "built in public, no vaporware": every claim needs a real test, and pull requests list honest limits.
7. **Out of scope, always:** life-safety systems, medical devices, vehicles on public roads, weapons, and anything that could hurt people without an independent hardware safety stop. The README must say so.

## 4. What exists today, to study

There is nothing for physical systems yet: no code and no public issue. [verified] Parts of RagLeap worth reading (read only; see section 2):

- `core/mcp_client.py` and `packages/ragleap-integrations`: the MCP client with an owner allowlist. [verified]
- `core/autonomy.py`: the one approval gate (`execute_or_request`). Modes are off, semi and full; sensitive roles are forced to semi; after an agent reads web or MCP content, outgoing actions need approval even in full mode (the taint rule). Data that comes from a device through MCP is untrusted in the same way. [verified]
- The sandbox runner `sandbox/runner.py`: a fixed container spec, no network, and the only component that holds the Docker socket. A good example of "the caller chooses nothing". [verified]
- `packages/ragleap-security` (see `docs/threat-model.md`), `packages/ragleap-tools`, `packages/ragleap-agents` (an act-observe loop, one action at a time), `packages/ragleap-memory` (tenant-scoped memory). [verified]
- How a package is organised and documented: `packages/ragleap-voice` and `packages/ragleap-phone/docs/` (a handover and a design note, like this one). [verified]
- The audit log and token budgets in the core, and the `ROADMAP.md`, `CONTRIBUTING.md` and `SECURITY.md` files.

## 5. Open-source projects to study

From memory, not rechecked [unverified]: MuJoCo, PyBullet, Gazebo and Webots (simulators); ROS 2 and its bridges (robot software); MQTT, OPC UA and Modbus (IoT and industrial protocols).

Rule: before choosing anything, check its licence, its current status, how heavy it is to install, and which Python versions it supports. Record third-party components in a `THIRD_PARTY_NOTICES.md` as `ragleap-voice` does. Review every licence before bundling anything, especially GPL and AGPL. Heavy engines arrive as optional extras or as separate services, never as a hard dependency. Understand their ideas; do not copy code. No simulator has been chosen. Choosing one is phase 0.

## 6. Proposed phases (each is done only with evidence)

| Phase | What | Done when |
|---|---|---|
| 0 | Design: the observation format, the command format, the capability levels, the safety envelope and a threat model. Compare 2 to 3 simulators or bridges (licence, install weight, repeatability, API stability, Python 3.10 or newer). | A written design merged, with the comparison and the reasons |
| 1 | Package skeleton and one simulator adapter, observe-only, with a tiny bundled test model | Tests pass in CI with no GPU and no display; the README says planned or pre-alpha; limits listed |
| 2 | An MCP server that offers observe tools, and a "propose action" tool that only returns a proposal | A real run where a RagLeap employee reads simulator state and answers, with a screenshot in the pull request |
| 3 | Simulated control with a safety envelope: commands go through the approval gate; limits are enforced by the bridge, not by the model; dry run before apply; check afterwards that the intended outcome really happened | Tests that try to break the envelope fail; a recorded demo |
| 4 | A second bridge, observe-only (for example ROS 2 with a simulated robot) | A real run against the simulated robot, with evidence |
| 5 | A first pilot with real hardware, observe-only first | All of these: named users and roles in the core (so every approval names a person), an independent hardware emergency stop, a written risk review, a tester from outside the project, and the maintainer's explicit go |
| 6 | Java and npm clients (section 8) | The Python interface is stable and the plan says what each adds |

## 7. Safety and privacy checklist

- The AI never talks to a motor directly. The path is: model, proposal, approval gate, the bridge's safety layer, device.
- The limits (speed, force, range, rate, workspace, allowed commands) live in the bridge, in one place. The model and tool calls cannot change them.
- The emergency stop is independent of the software and always works. The AI cannot override it.
- Simulation is not reality. Say so in the docs and in every claim.
- Data from devices and sensors is untrusted input and can carry instructions meant for the model. The taint rule applies.
- Cameras and sensors can record people. Consent and privacy law differ by country. Nobody on this project gives legal advice; each country needs its own check with sources. By default, record nothing (see issue #763 for the consent design).
- Devices belong to an organization; keep organizations isolated by default.
- Claims about large fleets or large scale need measured targets first. No measurement, no claim.
- Never put keys, device addresses, network details, recordings or photos of private places in the repository, issues, logs or screenshots.
- Report vulnerabilities privately through the repository's Security tab (see `SECURITY.md`), not in public issues.

## 8. Packaging: PyPI first, then Java and npm

**Python (first).** Layout as in the other packages [verified]: `packages/ragleap-physical/` with `pyproject.toml` (hatchling), `src/ragleap_physical/`, `tests/` (pytest), `README.md`, `LICENSE` (MIT), `CHANGELOG.md` (Keep a Changelog), `THIRD_PARTY_NOTICES.md`, optional `docs/` and `examples/`. Python 3.10 or newer, as every package here. The core of the package uses the standard library only; engines such as a simulator are optional extras. Pre-alpha classifier until real runs are tested.

Release steps are the maintainer's [verified in `release.yml`]: the workflow has one tag pattern, one manual-run option and one publish job per package, so adding `ragleap-physical` needs a small separate pull request (your lines only). PyPI needs a trusted publisher for the new project: owner `ragleap`, repository `ragleap-core`, workflow `release.yml`, environment `pypi` (and `testpypi`). The first upload goes through TestPyPI. Release tags are named `ragleap-physical-vX.Y.Z`; a plain core tag publishes nothing.

**Java (later) [plan].** The repository has Java ports under `java/` (ragleap-rag, ragleap-graph, ragleap-vectorstores), each with parity tests against the Python version. They use the group ID `io.github.antonyrag`; leave that as it is. Whether a new artifact uses it or a new namespace is the maintainer's decision, together with the Maven Central namespace verification. Start only when the Python interface is frozen and the plan states what Java adds, for example a client for the bridge protocol.

**npm (later) [plan].** Nothing exists in the repository today [verified: no `package.json`]. An npm account or organization, a scope name and trusted publishing with provenance need the maintainer. Start with a small client: types for observations and commands, and a client for the bridge. No native code.

**The rule for all three:** the safety envelope lives in one place only, the Python bridge. Java and npm are clients that talk to it; they never copy or weaken the safety logic. Keep the same name, `ragleap-physical`, in every registry where possible.

## 9. Coding style and conventions

Rules that exist in the repository today [verified]:
- Python, PEP 8-ish, not strictly enforced; readable code. A short docstring on new functions, especially when behaviour is not obvious.
- Branches `feat/...`, `fix/...`, `docs/...`. Commit messages start with `feat:`, `fix:` or `docs:`. Small, focused pull requests.
- CI must pass: `compile-check` and `docker-build-and-smoke-test` are required; about 37 checks run in total. Third-party GitHub Actions are pinned to commit hashes; keep it that way.

Proposed for this package (agree them in the first pull request) [plan]:
- Type hints on public functions; the adapter interface as a small abstract class.
- Unit tests never move real hardware and never need a network. Anything that needs a real device is a separate opt-in test, off by default.
- New opt-in environment flags are off by default and are added to `_FEATURE_FLAGS` in `tests/conftest.py` (a shared-file change, see section 2).
- Pull request description in four parts: **What / Limits / Tested / Not tested yet**. Be honest in Limits.
- Never mark something tested without a real run. Say exactly what was run.

## 10. The call for contributors

Contributors can bring: simulator models and scenarios, bridge adapters, real-robot test reports (a screenshot or short video, with private details hidden), documentation and translations, and safety reviews. Keep a table in the package docs: simulator or robot, contributor, what is done, link to the report. It starts empty and fills only from real reports. Rules: one contributor per adapter at a time; a claim that is quiet for a few weeks may be taken by someone else; everyone is credited by name unless they opt out.

## 11. Ways of working

- The maintainer is a founder in India; English is not the first language. Use simple words, short replies, one block per step, at most one question per reply, and no grand sketches. He watches token use.
- Read-only checks need no go. Anything public or that changes production or shared files needs an explicit go from the maintainer: merges, releases, posts and comments under his name, repository settings, spending money, removing anything.
- Never print or ask for secrets. Never write them in the repository.
- Use your own worktree for every task. Never edit the shared checkout. Never `git add -A`; add named files.
- Mark what is verified, planned or unverified. Own your mistakes plainly.
- Ask the maintainer how commands are run on your side (his own machine or a server).

## 12. First week

1. Read this file, `ROADMAP.md`, `CONTRIBUTING.md`, `SECURITY.md`, `core/mcp_client.py`, `core/autonomy.py`, `packages/ragleap-integrations`, `packages/ragleap-security/docs/threat-model.md`, `packages/ragleap-voice` (the layout) and `packages/ragleap-phone/docs/` (an example of a handover and a design note).
2. Ask the maintainer to open the public design issue (RFC) for this package, and answer the first comments.
3. Phase 0: try 2 simulators on a throwaway machine, never on production, and write the comparison.
4. Open the first code pull request: the package skeleton (`pyproject.toml`, `src/ragleap_physical/`, tests).

## 13. Open questions (nobody knows yet)

- Which simulator first, and how to ship test models with their licences checked.
- How the MCP server runs in the Docker setup (its own service, off by default?).
- What the safety envelope format looks like, and who reviews it.
- What Java and npm each add, and the namespace and scope decisions.
- Which real robot or test bench could host the first pilot, and who pays for it.
- Privacy and legal rules for cameras and CCTV, country by country.

## 14. Where this lives

This file lives at `packages/ragleap-physical/docs/HANDOVER.md`, next to a short README that says the package is planned and has no code yet. It is public, so it must stay free of anything private. Private matters (access, accounts, device details) are passed to you directly, never written in the repository.
