---
name: pdf-to-markdown
description: Extract the text of an existing binary document so it can be read in the conversation - a PDF, Word, PowerPoint or Excel file, an EPUB, an .msg email, a scanned or photographed page, or an audio recording - by running the local `tomd` command on it. Use only when the user points at a file that already exists and the answer depends on what is inside it: summarising a report, quoting a contract, pulling figures out of a sheet, reading slides, transcribing a recording. Do NOT use this skill to create, generate, write, edit, fill in or export a file in any of those formats - producing a .docx, .pptx, .xlsx or .pdf is the job of that format's own skill, and this skill must never turn such a request into Markdown instead.
---

# Reading an existing document with tomd

`tomd` wraps MarkItDown locally. It turns a binary document into Markdown **text
for reading**, so its contents can be quoted, summarised and searched.

## When not to use this

This skill answers "what does this file say". It has nothing to do with "make me
one of these".

| The user wants | Use |
| --- | --- |
| A Word document written, edited or filled in | the `docx` skill |
| A slide deck built or modified | the `pptx` skill |
| A spreadsheet created, cleaned or calculated | the `xlsx` skill |
| A PDF produced, merged, split or form-filled | the `pdf` skill |
| To know what an existing file **says** | this skill |

If the request is to *produce* a document, producing Markdown instead is a wrong
answer, not a convenient one. Hand the task to the skill that owns the format.

Plain text files — `.txt`, `.md`, `.csv`, `.json`, source code — need none of
this. Read them directly.

## One file

```bash
tomd "<path>" --stdout
```

`--stdout` prints the Markdown and writes nothing to disk. Read the result from
the command output. Quote the path: document names contain spaces far more often
than not.

## A large file

Do not pour a 200-page PDF into the conversation in one go.

```bash
tomd "<path>"
```

Without `--stdout` it writes `<same-name>.md` beside the original and prints a
one-line summary including the word count. Then read that `.md` file in pieces —
offset and limit, or a targeted grep — rather than all at once.

## Several files

```bash
tomd a.pdf b.docx c.xlsx --json
```

One JSON object per line on stdout, nothing else, so it can be parsed directly.
Each line carries `source`, `out_path`, `ok`, `cached`, `chars`, `words`,
`duration_ms` and `error`. A whole directory works too: `tomd folder/ -r --json`.

## When a conversion fails

The exit code is 1 if any file failed, and the failing file carries a populated
`error` — the rest of the batch still converts.

**Report the actual error to the user.** Do not invent plausible contents, and do
not report the document as empty: a failed conversion means tomd could not read
it, which is not the same as the file having nothing in it. A corrupt PDF, a
password-protected document and an unsupported format are different problems and
the error text says which one it is.

## When tomd is not installed

If the command is not found, tell the user and give them the install line:

```bash
uv tool install --with 'markitdown[all]' .
```

Do not quietly fall back to another tool, and do not guess at the file's contents
from its name. Say that the file cannot be read until `tomd` is available.

## Worth knowing

- Conversions are cached by content hash, so re-reading the same document is
  effectively free. A line reporting `cached` is normal, not a warning.
- Every converted document starts with a YAML front matter block recording the
  source path, the conversion time and the size. It is metadata, not content.
  Pass `--no-frontmatter` to omit it.
- When several documents in one directory share a name, the first takes
  `report.md` and the next becomes `report.docx.md`; the output says so.
