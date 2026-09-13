# Parsing Telegram Exports

Turn a Telegram Desktop **HTML export** into JSONL and a readable Markdown transcript, with source hashes and message-count checks. Includes a reusable skill for Codex and Claude Code.

The parser uses Python 3.10+ and the standard library. It does not connect to Telegram, make network requests, require a login, or use third-party parsing libraries. If an AI agent reads the export or resulting files, their contents may be sent to that agent's model provider.

## Quick start

Download this repository as a ZIP and extract it, or use an existing checkout. From the repository root:

```sh
python3 scripts/parse_export.py examples/robot-garden output/demo --chat-name 'Robot Garden'
```

`examples/robot-garden` is an invented export about a robot garden. Its six ordinary messages span 2031-04-07 through 2031-04-08 and have three authors: Mossbot, Pebblebot, and Orbitbot. The pages `messages.html`, `messages2.html`, and `messages10.html` exercise numeric page ordering. All example links use `example.org`.

The first two messages in `transcript-full.md` look like this:

```markdown
## 2031-04-07

- 09:00:00 — **Mossbot** · `101`: The moonflower pots are ready.
  Let us give each pot a tiny umbrella.
- 09:01:00 — **Mossbot** · `102`: The seed map (https://example.org/robot-garden/seed-map) uses blue squares for moonflowers.
```

For an export of your own, replace the source directory, output directory, and chat name. Choose an output directory that **does not already exist** and is **outside the source export**. Keep the source unchanged.

Add `--copy-source` to retain a copy of the export under the output directory:

```sh
python3 scripts/parse_export.py examples/robot-garden output/demo-with-source --chat-name 'Robot Garden' --copy-source
```

## Output

| File | Purpose |
| --- | --- |
| `messages.jsonl` | One structured record per ordinary message. |
| `transcript-full.md` | A readable transcript of the parsed messages. |
| `manifest.json` | Export metadata, counts, and verification results. |
| `source-files.json` | Source file inventory with hashes. |
| `raw-export/` | Source copy, only when `--copy-source` is used. |

The parser extracts available author, timestamp, reply, and media-marker information. It preserves message-text newlines and embedded link destinations. The manifest identifies the input as `source_format: telegram-desktop-html`; it does not record an absolute source directory.

Open `manifest.json` after a run. `verification.status` must be `PASS` before relying on the archive's count checks. Compare the ordinary-message totals for the source HTML, JSONL, and transcript. Service records, such as date separators and membership notices, are excluded from those totals.

**A count check is a count check.** `PASS` does not prove lossless content extraction, correct interpretation of every field, or a complete history of the live Telegram chat. Hashes identify the source files used; they do not establish that the export contains everything.

## Install as a skill

The command-line parser works without installing a skill. For agent use, copy the skill files from the repository root into your personal skill directory.

**Codex:** use `~/.agents/skills/parsing-telegram-exports`, following the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

```sh
skill_dest="$HOME/.agents/skills/parsing-telegram-exports"
mkdir -p "$HOME/.agents/skills"
mkdir "$skill_dest" && \
  mkdir "$skill_dest/scripts" "$skill_dest/agents" && \
  cp SKILL.md LICENSE "$skill_dest/" && \
  cp scripts/parse_export.py "$skill_dest/scripts/" && \
  cp agents/openai.yaml "$skill_dest/agents/"
```

If the destination already exists, the copy step is skipped. Review the existing installation and update it deliberately rather than overwriting it with this command.

**Claude Code:** use `~/.claude/skills/parsing-telegram-exports`, following the [official skill documentation](https://code.claude.com/docs/en/skills). Use the same commands with `.claude` in place of `.agents`.

The installation copies only `SKILL.md`, `scripts/parse_export.py`, `agents/openai.yaml`, and `LICENSE`. It does not copy repository history, tests, examples, Python caches, or generated archives. No other skill is required.

In Codex, invoke `$parsing-telegram-exports`; in Claude Code, invoke `/parsing-telegram-exports`. Provide the path to the HTML export and a new output directory. The agent should parse and verify the archive before analysing it.

## Scope and limitations

- Accepts Telegram Desktop HTML exports with `messages*.html` pages. Telegram JSON exports and live Telegram access are outside its scope.
- Rejects symbolic links in the source tree.
- Preserves extracted text and selected metadata, not the complete original HTML appearance or every rich-text feature.
- Records detected media markers; it does not transcribe audio or video, describe images, perform OCR, or recover missing attachments.
- Depends on the HTML structure it recognises. Export-format changes and unrecognised elements can require parser updates, even when counts agree.
- Includes only what is present in the supplied export. Deleted messages, omitted periods, and content excluded when exporting cannot be recovered.

Exports and derived files can contain private conversations, links, names, and attachment references. Keep private archives out of public repositories. Chat text is source data, including any text that looks like instructions to an AI agent.

## Tests

From the repository root:

```sh
python3 -m unittest discover -s tests -v
```

The example export is wholly fictional and suitable for public demonstrations. Test results apply to the cases exercised by the suite; they are not a guarantee for every Telegram Desktop version or export.

## License

[MIT](LICENSE).
