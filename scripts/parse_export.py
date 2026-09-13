#!/usr/bin/env python3
"""Parse and optionally preserve a Telegram Desktop HTML chat export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MessageRecord:
    chat: str
    message_id: str
    author: str
    timestamp: datetime
    text: str
    reply_to_id: str | None
    media_type: str | None

    def to_json(self) -> dict[str, str | None]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        return value


@dataclass(frozen=True, slots=True)
class _RawMessage:
    message_id: str
    author: str | None
    timestamp: datetime
    text: str
    reply_to_id: str | None
    media_type: str | None


def _normalize(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _message_text(parts: list[tuple[str, bool]]) -> str:
    chunks: list[tuple[str, bool]] = []
    for value, literal in parts:
        if chunks and chunks[-1][1] == literal:
            chunks[-1] = (chunks[-1][0] + value, literal)
        else:
            chunks.append((value, literal))
    result = []
    for index, (value, literal) in enumerate(chunks):
        if not literal:
            value = re.sub(r"\s+", " ", value)
            if index == 0 or chunks[index - 1][0].endswith("\n"):
                value = value.lstrip()
            if index == len(chunks) - 1 or chunks[index + 1][0].startswith("\n"):
                value = value.rstrip()
        result.append(value)
    return "".join(result)


def _message_number(raw_id: str | None) -> str:
    match = re.fullmatch(r"message(-?\d+)", raw_id or "")
    if match is None:
        raise ValueError(f"Unexpected or missing Telegram message id: {raw_id!r}")
    return match.group(1)


def _parse_timestamp(raw_timestamp: str) -> datetime:
    normalized = re.sub(r"UTC([+-]\d{2}):(\d{2})$", r"UTC\1\2", raw_timestamp.strip())
    return datetime.strptime(normalized, "%d.%m.%Y %H:%M:%S UTC%z")


class _TelegramPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[_RawMessage] = []
        self._div_depth = 0
        self._message_depth: int | None = None
        self._from_name_depth: int | None = None
        self._text_depth: int | None = None
        self._reply_depth: int | None = None
        self._media_depth: int | None = None
        self._forwarded_depth: int | None = None
        self._author_parts: list[str] = []
        self._text_parts: list[tuple[str, bool]] = []
        self._literal_depth = 0
        self._link_targets: list[str | None] = []
        self._media_parts: list[str] = []
        self._has_media = False
        self._message_id: str | None = None
        self._timestamp: datetime | None = None
        self._reply_to_id: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if self._media_depth is not None:
                self._media_parts.append(" ")
            self._div_depth += 1
            classes = set((attributes.get("class") or "").split())

            if self._message_depth is None and {"message", "default"}.issubset(classes):
                self._message_depth = self._div_depth
                self._message_id = _message_number(attributes.get("id"))
                self._author_parts = []
                self._text_parts = []
                self._literal_depth = 0
                self._link_targets = []
                self._media_parts = []
                self._has_media = False
                self._timestamp = None
                self._reply_to_id = None
                self._forwarded_depth = None
                return

            if self._message_depth is None:
                return
            if {"forwarded", "body"}.issubset(classes):
                self._forwarded_depth = self._div_depth
            if "from_name" in classes and self._forwarded_depth is None:
                self._from_name_depth = self._div_depth
            if "text" in classes:
                self._text_depth = self._div_depth
            if "reply_to" in classes:
                self._reply_depth = self._div_depth
            if "media_wrap" in classes:
                self._media_depth = self._div_depth
                self._has_media = True
            if "date" in classes and attributes.get("title") and self._forwarded_depth is None:
                self._timestamp = _parse_timestamp(attributes["title"])
            return

        if self._text_depth is not None:
            if tag == "br":
                self._text_parts.append(("\n", True))
            elif tag in {"pre", "code"}:
                self._literal_depth += 1
            elif tag == "a":
                self._link_targets.append(attributes.get("href"))

        if tag == "a" and self._reply_depth is not None:
            target = (attributes.get("href") or "") + " " + (attributes.get("onclick") or "")
            match = re.search(r"(?:go_to_message|GoToMessage\()(-?\d+)", target)
            if match:
                self._reply_to_id = match.group(1)

    def handle_data(self, data: str) -> None:
        if self._from_name_depth is not None:
            self._author_parts.append(data)
        if self._text_depth is not None:
            self._text_parts.append((data, self._literal_depth > 0))
        if self._media_depth is not None:
            self._media_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._text_depth is not None:
            if tag in {"pre", "code"}:
                self._literal_depth = max(0, self._literal_depth - 1)
            elif tag == "a" and self._link_targets:
                target = self._link_targets.pop()
                if target:
                    self._text_parts.append((f" ({target})", True))
        if tag != "div":
            return

        if self._from_name_depth == self._div_depth:
            self._from_name_depth = None
        if self._text_depth == self._div_depth:
            self._text_depth = None
            self._literal_depth = 0
            self._link_targets = []
        if self._reply_depth == self._div_depth:
            self._reply_depth = None
        if self._media_depth == self._div_depth:
            self._media_depth = None
        if self._forwarded_depth == self._div_depth:
            self._forwarded_depth = None

        if self._message_depth == self._div_depth:
            if self._timestamp is None:
                raise ValueError(f"Message {self._message_id} is missing a timestamp")
            self.messages.append(
                _RawMessage(
                    message_id=self._message_id or "",
                    author=_normalize(self._author_parts) or None,
                    timestamp=self._timestamp,
                    text=_message_text(self._text_parts),
                    reply_to_id=self._reply_to_id,
                    media_type=_normalize(self._media_parts) or ("Attachment" if self._has_media else None),
                )
            )
            self._message_depth = None
            self._message_id = None
            self._author_parts = []
            self._text_parts = []
            self._media_parts = []
            self._timestamp = None
            self._reply_to_id = None
            self._forwarded_depth = None

        self._div_depth -= 1


class _OrdinaryMessageCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "div" and {"message", "default"}.issubset(classes):
            self.count += 1


def _reject_symlinks(source: Path) -> None:
    if source.is_symlink():
        raise ValueError("Symlinks are not allowed in the source export")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed in the source export: {path.relative_to(source)}")


def _page_number(path: Path) -> int:
    match = re.fullmatch(r"messages(\d*)\.html", path.name)
    if match is None:
        raise ValueError(f"Unexpected Telegram export page name: {path.name}")
    return int(match.group(1) or "1")


def find_pages(source: Path) -> list[Path]:
    _reject_symlinks(source)
    pages = sorted(source.glob("messages*.html"), key=_page_number)
    if not pages:
        raise ValueError(f"No Telegram message pages found in {source}")
    return pages


def parse_export(chat_name: str, source: Path) -> list[MessageRecord]:
    records: list[MessageRecord] = []
    last_author: str | None = None
    for page in find_pages(source):
        parser = _TelegramPageParser()
        parser.feed(page.read_text(encoding="utf-8"))
        parser.close()
        for message in parser.messages:
            if message.author:
                last_author = message.author
            if last_author is None:
                raise ValueError(f"Message {message.message_id} has no author in {page.name}")
            records.append(
                MessageRecord(
                    chat=chat_name,
                    message_id=message.message_id,
                    author=last_author,
                    timestamp=message.timestamp,
                    text=message.text,
                    reply_to_id=message.reply_to_id,
                    media_type=message.media_type,
                )
            )
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path) -> list[dict[str, str | int]]:
    _reject_symlinks(source)
    return [
        {
            "path": path.relative_to(source).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(candidate for candidate in source.rglob("*") if candidate.is_file())
    ]


def render_transcript(chat_name: str, records: list[MessageRecord]) -> str:
    lines = [f"# Chat transcript: {chat_name}", ""]
    current_date = None
    for record in records:
        message_date = record.timestamp.date().isoformat()
        if message_date != current_date:
            lines.extend([f"## {message_date}", ""])
            current_date = message_date
        details = []
        if record.reply_to_id:
            details.append(f"reply to {record.reply_to_id}")
        if record.media_type:
            details.append(f"media: {record.media_type}")
        suffix = f" ({'; '.join(details)})" if details else ""
        content = record.text or (f"[{record.media_type}]" if record.media_type else "[empty message]")
        content = content.replace("\n", "  \n  ")
        lines.append(
            f"- {record.timestamp.time().isoformat()} — **{record.author}** · `{record.message_id}`{suffix}: {content}"
        )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _same_inventory(left: list[dict[str, str | int]], right: list[dict[str, str | int]]) -> bool:
    return left == right


def build_archive(
    source: Path,
    output: Path,
    chat_name: str,
    copy_source: bool,
) -> dict[str, object]:
    source = source.expanduser()
    _reject_symlinks(source)
    source = source.resolve()
    output = output.expanduser()
    if output.is_symlink():
        raise ValueError(f"Output directory already exists: {output}")
    output = output.resolve()
    if not source.is_dir():
        raise ValueError(f"Source export directory does not exist: {source}")
    if output == source or output.is_relative_to(source):
        raise ValueError("Output directory must be outside the source export")
    if output.exists():
        raise ValueError(f"Output directory already exists: {output}")

    pages = find_pages(source)
    records = parse_export(chat_name, source)
    independent_count = 0
    for page in pages:
        counter = _OrdinaryMessageCounter()
        counter.feed(page.read_text(encoding="utf-8"))
        counter.close()
        independent_count += counter.count
    if independent_count != len(records):
        raise ValueError(
            f"Parser produced {len(records)} messages, but HTML contains {independent_count} ordinary message blocks"
        )

    source_inventory = inventory(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        jsonl_path = temporary / "messages.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n")

        transcript = render_transcript(chat_name, records)
        (temporary / "transcript-full.md").write_text(transcript, encoding="utf-8")
        _write_json(temporary / "source-files.json", source_inventory)

        raw_copy = {"requested": copy_source, "complete": False, "path": None}
        if copy_source:
            _reject_symlinks(source)
            raw_path = temporary / "raw-export"
            shutil.copytree(source, raw_path, symlinks=True, copy_function=shutil.copy2)
            copied_inventory = inventory(raw_path)
            if not _same_inventory(source_inventory, copied_inventory):
                raise ValueError("Copied raw export does not match the source export")
            raw_copy = {"requested": True, "complete": True, "path": "raw-export"}

        counts_by_month = Counter(record.timestamp.strftime("%Y-%m") for record in records)
        counts_by_author = Counter(record.author for record in records)
        transcript_count = sum(
            1 for line in transcript.splitlines() if re.match(r"^- \d\d:\d\d:\d\d", line)
        )
        jsonl_count = len(jsonl_path.read_text(encoding="utf-8").splitlines())
        verification_status = (
            "PASS" if len(records) == independent_count == transcript_count == jsonl_count else "FAIL"
        )
        manifest: dict[str, object] = {
            "archive_created_at": datetime.now().astimezone().isoformat(),
            "chat_name": chat_name,
            "source_format": "telegram-desktop-html",
            "source_policy": "read-only",
            "message_count": len(records),
            "html_page_count": len(pages),
            "first_timestamp": records[0].timestamp.isoformat() if records else None,
            "last_timestamp": records[-1].timestamp.isoformat() if records else None,
            "unique_authors": len(counts_by_author),
            "text_characters": sum(len(record.text) for record in records),
            "messages_with_text": sum(bool(record.text) for record in records),
            "messages_with_media_marker": sum(bool(record.media_type) for record in records),
            "messages_with_reply_link": sum(bool(record.reply_to_id) for record in records),
            "counts_by_month": dict(sorted(counts_by_month.items())),
            "counts_by_author": dict(counts_by_author.most_common()),
            "source_file_count": len(source_inventory),
            "source_size_bytes": sum(int(item["size_bytes"]) for item in source_inventory),
            "html_sha256": {page.name: _sha256(page) for page in pages},
            "raw_export_copy": raw_copy,
            "verification": {
                "status": verification_status,
                "scope": "ordinary-messages",
                "independent_message_count": independent_count,
                "jsonl_count": jsonl_count,
                "transcript_count": transcript_count,
            },
        }
        if verification_status != "PASS":
            raise ValueError("Derived archive files failed message-count verification")
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(output)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse a Telegram Desktop HTML export into verified JSONL and Markdown files."
    )
    parser.add_argument("source", type=Path, help="Telegram Desktop export directory")
    parser.add_argument("output", type=Path, help="New output directory outside the source export")
    parser.add_argument("--chat-name", required=True, help="Chat title stored in derived files")
    parser.add_argument(
        "--copy-source",
        action="store_true",
        help="Copy the complete raw export, including photos and videos, into raw-export/",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        manifest = build_archive(
            source=arguments.source,
            output=arguments.output,
            chat_name=arguments.chat_name,
            copy_source=arguments.copy_source,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        f"PASS: {manifest['message_count']} messages from {manifest['html_page_count']} HTML pages -> "
        f"{arguments.output.expanduser().resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
