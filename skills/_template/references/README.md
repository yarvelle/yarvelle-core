# Skill References Directory

Place static reference documents (Markdown, TXT, or JSON files) in this folder.

When an agent loads this skill and has the `skill-docs` tool enabled, the model can dynamically inspect these files at runtime by invoking:
```json
{
  "skill_id": "_template",
  "doc": "example.md"
}
```

Keep reference documents factual, modular, and focused on educational or administrative reference data.
