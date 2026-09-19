---
name: pdf-to-markdown
description: Read the contents of a non-text file the user attached or named - PDF, DOCX, PPTX, XLSX, XLS, CSV, EPUB, MSG, a scanned or photographed image (PNG, JPG), or audio (MP3, WAV, M4A) - by converting it to Markdown with the local `tomd` command first. Use whenever answering needs what is inside such a file: summarising a PDF, pulling figures out of a spreadsheet, quoting a contract, reading slides, or transcribing a recording. Do not open these formats with a text reader; their bytes are not text.
---

# Reading non-text files with tomd

`tomd` wraps MarkItDown locally. It turns binary documents into Markdown so their
contents can be read like any other text.

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
- `.md` files are never converted into themselves; read those directly.
