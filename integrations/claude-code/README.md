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

The skill above already covers this, and a global rule is the riskier way to say
it: an unconditional "convert these formats" line competes with the skills that
*create* Word documents, decks and spreadsheets, and can turn a request for a
.docx into a .md. Paste this only if you want the behaviour stated globally as
well, and note the second sentence, which is what keeps it in its lane:

```markdown
## Reading non-text files

To read what an existing PDF, Word, PowerPoint, Excel, image or audio file says,
convert it first: `tomd "<path>" --stdout`, or `tomd "<path>"` for a large one,
then read the `.md` it writes. This is for reading only - when the task is to
create or edit a file in one of those formats, use that format's own skill and
do not substitute Markdown. If `tomd` is missing, say so rather than falling
back to another tool.
```
