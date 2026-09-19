# Claude Code integration

Two pieces of configuration live here. Neither is installed automatically; the
global Claude Code configuration belongs to you, not to this repository.

## 1. The skill

`pdf-to-markdown/SKILL.md` teaches Claude Code to convert a binary document with
`tomd` before trying to read it. Install it by copying the directory:

```bash
cp -r integrations/claude-code/pdf-to-markdown ~/.claude/skills/
```

## 2. The CLAUDE.md block

Paste this into `~/.claude/CLAUDE.md`:

```markdown
## Non-text files

Any file that is not plain text - PDF, DOCX, PPTX, XLSX, images, audio - must be
converted before being read: `tomd "<path>" --stdout`, or `tomd "<path>"` for a
large one, then read the `.md` it writes. Never open these formats with a text
reader and never guess at their contents.
If `tomd` is missing, say so instead of falling back to another tool.
```
