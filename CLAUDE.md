# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The canonical agent guide lives in AGENTS.md (single source of truth for all
agents working here):

@AGENTS.md

Claude Code specifics:

- Slate's own enforcement hooks (`slate setup claude`) are **not** installed
  in this repo yet — dogfooding starts once v0.1 is merged and published.
- When touching `src/slate/commands/hook.py` or `src/slate/sessions.py`,
  remember these run inside *other people's* Claude Code sessions: fail-open
  (exit 0, no output, log the traceback) is a hard requirement, not a style
  preference.
