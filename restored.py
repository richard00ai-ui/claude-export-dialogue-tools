#!/usr/bin/env python3
"""
Convert a Claude export archive into a dialogue-folder workspace.

Pipeline:
1. Extract a Claude export zip.
2. Decode unicode-escaped content.
3. Build an English-named project/conversation workspace.

Script-defined filenames and Markdown boilerplate are English-only. Names that
come from the decoded export, such as project and conversation folder names,
preserve their source language after filesystem-safe cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
UNCLASSIFIED_PROJECT = "未分类对话"

ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
HAN_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
SAFE_ASCII = re.compile(r"[^a-z0-9_-]+")
UNICODE_ESCAPE_RUN = re.compile(r"(?:\\u[0-9a-fA-F]{4})+")
BYTE_ESCAPE_RUN = re.compile(r"(?:\\x[0-9a-fA-F]{2}){2,}")

EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "project",
    "conversation",
    "claude",
    "richard",
    "current",
    "context",
    "purpose",
    "state",
    "tools",
    "resources",
}

ZH_STOPWORDS = {
    "\u8fd9\u4e2a",
    "\u90a3\u4e2a",
    "\u9879\u76ee",
    "\u5bf9\u8bdd",
    "\u8ba8\u8bba",
    "\u5206\u6790",
    "\u4ec0\u4e48",
    "\u5982\u4f55",
    "\u53ef\u4ee5",
    "\u9700\u8981",
    "\u5f53\u524d",
    "\u5df2\u7ecf",
    "\u8fdb\u884c",
    "\u4e00\u4e2a",
    "\u76f8\u5173",
    "\u5185\u5bb9",
}


@dataclass
class ProjectInfo:
    uuid: str
    source_name: str
    description: str
    slug: str
    source_dir: str
    created_at: str | None
    updated_at: str | None
    docs: list[dict[str, Any]]
    memory: str
    keywords: Counter[str]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def decode_unicode_escapes_in_string(text: str) -> str:
    if "\\u" not in text and "\\x" not in text:
        return text

    def replace_unicode(match: re.Match[str]) -> str:
        sequence = match.group(0)
        try:
            return json.loads(f'"{sequence}"')
        except json.JSONDecodeError:
            return sequence

    def replace_bytes(match: re.Match[str]) -> str:
        sequence = match.group(0)
        try:
            raw = bytes(int(part, 16) for part in re.findall(r"\\x([0-9a-fA-F]{2})", sequence))
            decoded = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return sequence
        if decoded and not any(char in decoded for char in "\ufffd"):
            return decoded
        return sequence

    text = UNICODE_ESCAPE_RUN.sub(replace_unicode, text)
    return BYTE_ESCAPE_RUN.sub(replace_bytes, text)


def deep_decode(value: Any) -> Any:
    if isinstance(value, str):
        return decode_unicode_escapes_in_string(value)
    if isinstance(value, list):
        return [deep_decode(item) for item in value]
    if isinstance(value, dict):
        return {key: deep_decode(item) for key, item in value.items()}
    return value


def load_decoded_json(path: Path) -> Any:
    return deep_decode(json.loads(path.read_text(encoding="utf-8")))


def materialize_decoded_source(source: Path, decoded_dir: Path, force: bool) -> Path:
    if decoded_dir.exists() and force:
        shutil.rmtree(decoded_dir)
    if decoded_dir.exists() and (decoded_dir / "conversations.json").exists():
        return decoded_dir

    if decoded_dir.exists():
        shutil.rmtree(decoded_dir)
    decoded_dir.mkdir(parents=True, exist_ok=True)

    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = decoded_dir / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if item.name == ".DS_Store":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() == ".json":
            write_json(target, load_decoded_json(item))
        else:
            shutil.copy2(item, target)

    return decoded_dir


def safe_extract(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        resolved_root = extract_dir.resolve()
        for member in archive.infolist():
            target = extract_dir / member.filename
            resolved_target = target.resolve()
            if resolved_root != resolved_target and resolved_root not in resolved_target.parents:
                raise RuntimeError(f"Unsafe zip path: {member.filename}")
        archive.extractall(extract_dir)

    if (extract_dir / "conversations.json").exists():
        return extract_dir

    candidates = [
        path
        for path in extract_dir.iterdir()
        if path.is_dir() and (path / "conversations.json").exists()
    ]
    if len(candidates) == 1:
        return candidates[0]

    raise RuntimeError(f"Could not find conversations.json under {extract_dir}")


def resolve_source(input_path: Path, extract_dir: Path, force_extract: bool) -> Path:
    input_path = input_path.expanduser()
    if input_path.is_dir():
        return input_path
    if input_path.suffix.lower() != ".zip":
        raise RuntimeError(f"Input must be a directory or .zip file: {input_path}")
    if extract_dir.exists() and force_extract:
        shutil.rmtree(extract_dir)
    if extract_dir.exists() and (extract_dir / "conversations.json").exists():
        return extract_dir
    return safe_extract(input_path, extract_dir)


def ascii_slug(value: object, fallback: str, max_len: int = 64) -> str:
    text = "" if value is None else str(value)
    text = text.lower().strip()
    text = SAFE_ASCII.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if not text:
        text = fallback
    if len(text) > max_len:
        text = text[:max_len].rstrip("-_")
    return text or fallback


def unique_slug(base: str, used: set[str]) -> str:
    slug = base
    index = 2
    while slug in used:
        slug = f"{base}-{index}"
        index += 1
    used.add(slug)
    return slug


def source_slug(value: object, fallback: str, max_len: int = 72) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    if not text:
        text = fallback
    text = text.replace("/", "／").replace("\\", "＼").replace(":", "：")
    text = re.sub(r"[\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(" .-_")
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .-_")
    return text or fallback


def source_filename(value: object, fallback: str) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    if not text:
        text = fallback
    text = text.replace("/", "／").replace("\\", "＼")
    text = re.sub(r"[\x00-\x1f]", "_", text).strip(" .")
    return text or fallback


def timestamp_prefix(value: object) -> str:
    if not value:
        return "no-date"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return ascii_slug(text[:19], "no-date")


def content_to_markdown(content: Any) -> str:
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            if block.get("text") is not None:
                parts.append(str(block["text"]))
            else:
                parts.append("```json\n" + json.dumps(block, ensure_ascii=False, indent=2) + "\n```")
    elif content:
        parts.append(str(content))
    return "\n\n".join(parts)


def message_body(message: dict[str, Any]) -> str:
    return message.get("text") or content_to_markdown(message.get("content")) or ""


def named_file_or_attachment(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    for item in values:
        if not isinstance(item, dict):
            continue
        for key in ["file_name", "filename", "name", "title"]:
            value = str(item.get(key) or "").strip()
            if value:
                return value
    return ""


def file_extension_from_type(file_type: str) -> str:
    normalized = file_type.lower().strip()
    if "markdown" in normalized:
        return ".md"
    if "json" in normalized:
        return ".json"
    if "python" in normalized:
        return ".py"
    if "csv" in normalized:
        return ".csv"
    if "html" in normalized:
        return ".html"
    return ".txt"


def write_conversation_files(conversation_dir: Path, messages: list[dict[str, Any]]) -> int:
    files_dir = conversation_dir / "files"
    used_names: set[str] = set()
    written = 0

    for message_number, message in enumerate(messages, 1):
        for source_key in ["attachments", "files"]:
            for item_number, item in enumerate(message.get(source_key) or [], 1):
                if not isinstance(item, dict):
                    continue
                content = item.get("extracted_content")
                if content is None:
                    continue
                content_text = str(content)
                if not content_text.strip():
                    continue

                filename = source_filename(
                    item.get("file_name") or item.get("filename") or item.get("name"),
                    f"{source_key[:-1]}-message-{message_number:03d}-{item_number:02d}{file_extension_from_type(str(item.get('file_type') or ''))}",
                )
                if "." not in Path(filename).name:
                    filename = f"{filename}{file_extension_from_type(str(item.get('file_type') or ''))}"

                original_filename = filename
                suffix = 2
                while filename in used_names:
                    stem = Path(original_filename).stem
                    ext = Path(original_filename).suffix
                    filename = f"{stem}-{suffix}{ext}"
                    suffix += 1
                used_names.add(filename)
                write_text(files_dir / filename, content_text.rstrip() + "\n")
                written += 1

    return written


def conversation_has_content(conversation: dict[str, Any]) -> bool:
    if str(conversation.get("name") or "").strip():
        return True
    if str(conversation.get("summary") or "").strip():
        return True
    for message in conversation.get("chat_messages") or []:
        if message_body(message).strip():
            return True
        for values in [message.get("attachments"), message.get("files")]:
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and str(item.get("extracted_content") or "").strip():
                        return True
        if named_file_or_attachment(message.get("attachments")):
            return True
        if named_file_or_attachment(message.get("files")):
            return True
    return False


def conversation_title(conversation: dict[str, Any], fallback: str) -> str:
    title = str(conversation.get("name") or "").strip()
    if title:
        return title
    summary = str(conversation.get("summary") or "").strip()
    if summary:
        return summary[:48]
    for message in conversation.get("chat_messages") or []:
        body = message_body(message).strip()
        if body:
            return body[:48]
        attachment_name = named_file_or_attachment(message.get("attachments"))
        if attachment_name:
            return attachment_name[:48]
        file_name = named_file_or_attachment(message.get("files"))
        if file_name:
            return file_name[:48]
    return fallback


def tokenize(text: str) -> Counter[str]:
    tokens: Counter[str] = Counter()
    lowered = text.lower()
    for word in ASCII_WORD.findall(lowered):
        if word not in EN_STOPWORDS:
            tokens[word] += 1
    for run in HAN_RUN.findall(text):
        if run not in ZH_STOPWORDS:
            tokens[run] += 2
        if len(run) >= 4:
            for i in range(len(run) - 1):
                gram = run[i : i + 2]
                if gram not in ZH_STOPWORDS:
                    tokens[gram] += 1
            for i in range(len(run) - 2):
                gram = run[i : i + 3]
                if gram not in ZH_STOPWORDS:
                    tokens[gram] += 1
    return tokens


def top_keywords(counter: Counter[str], limit: int = 80) -> Counter[str]:
    return Counter(dict(counter.most_common(limit)))


def score_conversation(project: ProjectInfo, conversation: dict[str, Any]) -> int:
    text = "\n".join(
        str(part)
        for part in [
            conversation.get("name"),
            conversation.get("summary"),
        ]
        if part
    )
    conv_tokens = tokenize(text)
    if not conv_tokens:
        return 0
    score = 0
    for token, count in conv_tokens.items():
        score += min(count, 3) * min(project.keywords.get(token, 0), 5)
    return score


def load_classification_map(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = load_decoded_json(path.expanduser())
    if isinstance(data, dict) and isinstance(data.get("assignments"), dict):
        data = data["assignments"]
    if not isinstance(data, dict):
        raise RuntimeError(f"Classification map must be a JSON object: {path}")
    result: dict[str, str] = {}
    for key, value in data.items():
        conv_uuid = str(key or "").strip()
        target = str(value or "").strip()
        if conv_uuid and target:
            result[conv_uuid] = target
    return result


def resolve_manual_project_slug(target: str, projects: list[ProjectInfo]) -> str | None:
    normalized = target.strip()
    if not normalized:
        return None
    if normalized in {UNCLASSIFIED_PROJECT, "unclassified"}:
        return UNCLASSIFIED_PROJECT
    lowered = normalized.lower()
    for project in projects:
        candidates = {
            project.uuid,
            project.slug,
            project.source_name,
            ascii_slug(project.source_name, ""),
        }
        if normalized in candidates or lowered in {item.lower() for item in candidates if item}:
            return project.slug
    return None


def copy_source_project_files(project_dir: Path, source_project_dir: Path) -> None:
    target_root = project_dir / "references" / "files"
    if not source_project_dir.exists():
        return
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    for item in sorted(source_project_dir.iterdir()):
        if item.name == ".DS_Store":
            continue
        shutil.copytree(item, target_root / item.name) if item.is_dir() else shutil.copy2(item, target_root / item.name)


def build_projects(
    source: Path,
    output: Path,
    keep_decoded_json: bool,
) -> list[ProjectInfo]:
    project_files = sorted((source / "projects").glob("*.json")) if (source / "projects").exists() else []
    memories_path = source / "memories.json"
    memories = load_decoded_json(memories_path) if memories_path.exists() else []
    first_memory = memories[0] if memories else {}
    project_memories = first_memory.get("project_memories") or {}

    projects: list[ProjectInfo] = []
    used_slugs: set[str] = set()

    for file_path in project_files:
        data = load_decoded_json(file_path)
        uuid = data.get("uuid") or file_path.stem
        source_name = data.get("name") or f"project-{uuid[:8]}"
        description = data.get("description") or ""
        base_slug = source_slug(source_name, f"project-{uuid[:8]}")
        slug = unique_slug(base_slug, used_slugs)
        docs = data.get("docs") or []
        memory = project_memories.get(uuid, "")
        profile_text = "\n".join(
            [source_name, description, memory]
            + [str(doc.get("filename") or "") + "\n" + str(doc.get("content") or "") for doc in docs]
        )
        projects.append(
            ProjectInfo(
                uuid=uuid,
                source_name=source_name,
                description=description,
                slug=slug,
                source_dir=f"projects/{file_path.name}",
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
                docs=docs,
                memory=memory,
                keywords=top_keywords(tokenize(profile_text)),
            )
        )

    return projects


def project_has_content(project: ProjectInfo, conversations: list[dict[str, Any]]) -> bool:
    if conversations:
        return True
    if project.description.strip() or project.memory.strip():
        return True
    for doc in project.docs:
        if str(doc.get("filename") or "").strip() or str(doc.get("content") or "").strip():
            return True
    return False


def write_project_files(
    source: Path,
    output: Path,
    projects: list[ProjectInfo],
    assignments: dict[str, list[dict[str, Any]]],
    keep_decoded_json: bool,
) -> int:
    skipped_empty = 0
    for project in projects:
        conversations = assignments.get(project.slug, [])
        if not project_has_content(project, conversations):
            skipped_empty += 1
            continue

        project_dir = output / "projects" / project.slug
        (project_dir / "conversations").mkdir(parents=True, exist_ok=True)

        write_text(
            project_dir / "memory.md",
            "\n".join(
                [
                    f"# {project.slug} memory",
                    "",
                    "## Source",
                    "",
                    f"- Source name: {project.source_name}",
                    f"- Source UUID: {project.uuid}",
                    "",
                    "## Stable context",
                    "",
                    project.memory.strip() or "No project memory was found in the Claude export.",
                    "",
                ]
            ),
        )

        copy_source_project_files(project_dir, source / project.source_dir.removesuffix(".json"))
        docs_dir = project_dir / "references" / "files"
        used_doc_names: set[str] = set()
        for doc_index, doc in enumerate(project.docs, 1):
            filename = source_filename(doc.get("filename"), f"document-{doc_index:04d}.md")
            if "." not in Path(filename).name:
                filename = f"{filename}.md"
            original_filename = filename
            suffix = 2
            while filename in used_doc_names:
                stem = Path(original_filename).stem
                ext = Path(original_filename).suffix
                filename = f"{stem}-{suffix}{ext}"
                suffix += 1
            used_doc_names.add(filename)
            write_text(docs_dir / filename, doc.get("content") or "")
        if keep_decoded_json:
            write_json(project_dir / "references" / "project.json", load_decoded_json(source / project.source_dir))

    return skipped_empty


def classify_conversations(
    source: Path,
    output: Path,
    projects: list[ProjectInfo],
    keep_decoded_json: bool,
    min_score: int,
    classification_map: dict[str, str],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    conversations_path = source / "conversations.json"
    conversations = load_decoded_json(conversations_path) if conversations_path.exists() else []
    assignments: dict[str, list[dict[str, Any]]] = {project.slug: [] for project in projects}
    assignments[UNCLASSIFIED_PROJECT] = []
    skipped_empty = 0

    for index, conversation in enumerate(conversations, 1):
        uuid = conversation.get("uuid") or f"conversation-{index:04d}"
        if not conversation_has_content(conversation):
            skipped_empty += 1
            continue
        scores = [(project, score_conversation(project, conversation)) for project in projects]
        best_project, best_score = max(scores, key=lambda item: item[1]) if scores else (None, 0)
        manual_target = classification_map.get(str(uuid))
        manual_slug = resolve_manual_project_slug(manual_target, projects) if manual_target else None
        slug = manual_slug or (best_project.slug if best_project and best_score >= min_score else UNCLASSIFIED_PROJECT)
        item = dict(conversation)
        item["_classified_project"] = slug
        item["_classification_score"] = best_score
        item["_classification_source"] = "manual" if manual_slug else "score"
        assignments[slug].append(item)

        title_slug = source_slug(conversation_title(conversation, f"conversation-{uuid[:8]}"), f"conversation-{uuid[:8]}", 48)
        conversation_dir = (
            output
            / "projects"
            / slug
            / "conversations"
            / f"{title_slug}_{timestamp_prefix(conversation.get('created_at'))}_{uuid[:8]}"
        )
        conversation_dir.mkdir(parents=True, exist_ok=True)

        messages = conversation.get("chat_messages") or []
        write_text(
            conversation_dir / "summary.md",
            "\n".join(
                [
                    f"# Conversation summary",
                    "",
                    "## Source",
                    "",
                    f"- Title: {conversation.get('name') or ''}",
                    f"- UUID: {uuid}",
                    f"- Classified project: {slug}",
                    f"- Classification score: {best_score}",
                    f"- Classification source: {'manual' if manual_slug else 'score'}",
                    "",
                    "## Summary",
                    "",
                    conversation.get("summary") or "No summary was included in the export.",
                    "",
                    "## Next lookup",
                    "",
                    "- See `transcript.md` for the full decoded conversation.",
                    "",
                ]
            ),
        )

        transcript_lines = [
            "# Conversation transcript",
            "",
            f"- Source title: {conversation.get('name') or ''}",
            f"- Source UUID: {uuid}",
            "",
        ]
        for message_number, message in enumerate(messages, 1):
            body = message_body(message)
            transcript_lines += [
                f"## Message {message_number}",
                "",
                f"- Sender: {message.get('sender') or 'unknown'}",
                f"- Created at: {message.get('created_at') or ''}",
                "",
                body,
                "",
            ]
        for label, key in [("Attachments", "attachments"), ("Files", "files")]:
            values = message.get(key) or []
            if values:
                transcript_lines += [f"### {label}", "", "```json", json.dumps(values, ensure_ascii=False, indent=2), "```", ""]
        write_text(conversation_dir / "transcript.md", "\n".join(transcript_lines).rstrip() + "\n")
        write_conversation_files(conversation_dir, messages)

        if keep_decoded_json:
            write_json(conversation_dir / "source-conversation.json", conversation)

    return assignments, skipped_empty


def write_root_files(
    output: Path,
    source: Path,
    projects: list[ProjectInfo],
    assignments: dict[str, list[dict[str, Any]]],
) -> None:
    memories_path = source / "memories.json"
    memories = load_decoded_json(memories_path) if memories_path.exists() else []
    global_memory = memories[0].get("conversations_memory", "") if memories else ""
    total_conversations = sum(len(items) for items in assignments.values())

    write_text(
        output / "README.md",
        "\n".join(
            [
                "# Dialogue folder export",
                "",
                "This workspace was generated from a Claude export archive.",
                "",
                "## Structure",
                "",
                "- `memory.md`: global conversation memory from the export.",
                "- `projects/`: project folders with classified conversations.",
                "",
                "## Counts",
                "",
                f"- Projects: {len(projects)}",
                f"- Conversations: {total_conversations}",
                "",
                "## Notes",
                "",
                "Script-defined structure names are English-only.",
                "Decoded source names and content preserve their source language.",
                "",
            ]
        ),
    )

    write_text(
        output / "memory.md",
        "\n".join(
            [
                "# Global memory",
                "",
                "## Source conversation memory",
                "",
                global_memory.strip() or "No global conversation memory was found in the export.",
                "",
            ]
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a Claude export into an English-named dialogue folder workspace.")
    parser.add_argument("archive_or_dir", type=Path, help="Claude export zip or extracted directory")
    parser.add_argument("--output", type=Path, default=Path("restored"), help="Output workspace directory")
    parser.add_argument("--work-dir", type=Path, default=Path(".claude-export-work"), help="Working directory for zip extraction")
    parser.add_argument("--force", action="store_true", help="Recreate work-dir and output before running")
    parser.add_argument("--keep-work-dir", action="store_true", help="Keep temporary extraction and decoded JSON files")
    parser.add_argument("--keep-decoded-json", action="store_true", help="Keep decoded JSON copies in the generated workspace")
    parser.add_argument("--min-score", type=int, default=2, help="Minimum classification score before using the fallback folder")
    parser.add_argument("--classification-map", type=Path, help="JSON file exported from classification-reviewer.html")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.force:
        if args.work_dir.exists():
            shutil.rmtree(args.work_dir)
        if args.output.exists():
            shutil.rmtree(args.output)

    args.output.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    source_hash = hashlib.sha1(str(args.archive_or_dir.resolve()).encode("utf-8")).hexdigest()[:10]
    extract_dir = args.work_dir / f"extract-{source_hash}"
    raw_source = resolve_source(args.archive_or_dir, extract_dir, args.force)
    decoded_dir = args.work_dir / f"decoded-{source_hash}"
    source = materialize_decoded_source(raw_source, decoded_dir, args.force)

    projects = build_projects(source, args.output, args.keep_decoded_json)
    classification_map = load_classification_map(args.classification_map)
    assignments, skipped_empty = classify_conversations(
        source,
        args.output,
        projects,
        args.keep_decoded_json,
        args.min_score,
        classification_map,
    )
    skipped_empty_projects = write_project_files(source, args.output, projects, assignments, args.keep_decoded_json)
    active_projects = [project for project in projects if project_has_content(project, assignments.get(project.slug, []))]
    write_root_files(args.output, source, active_projects, assignments)

    print(f"raw_source={raw_source}")
    print(f"decoded_source={source}")
    print(f"output={args.output}")
    print(f"projects={len(active_projects)}")
    print(f"conversations={sum(len(items) for items in assignments.values())}")
    print(f"unclassified={len(assignments.get(UNCLASSIFIED_PROJECT, []))}")
    print(f"skipped_empty={skipped_empty}")
    print(f"skipped_empty_projects={skipped_empty_projects}")
    print(f"manual_assignments={len(classification_map)}")

    if not args.keep_work_dir and args.work_dir.exists():
        shutil.rmtree(args.work_dir)
        print(f"removed_work_dir={args.work_dir}")


if __name__ == "__main__":
    main()
