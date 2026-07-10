# Claude export dialogue pipeline

把 Claude export zip 转成 dialogue-folder 工作区。

## Usage

在桌面创建一个文件夹，命名为 `claude备份`。

把这些文件放进 `claude备份`：

- `restored.py`
- `classification-reviewer.html`
- `claude-export.zip`，也就是从 Claude 获取到的数据压缩包，请重命名成这个名字

如果你想先人工复核项目归属并直接导出文件夹：

1. 双击打开 `classification-reviewer.html`。
2. 拖入 `claude-export.zip`。
3. 在页面里调整错分的对话。
4. 点击 `以文件夹的形式导出`，选择保存位置。

打开终端，运行：

```bash
cd ~/Desktop/claude备份
python3 restored.py claude-export.zip --output restored --work-dir work --force
```

运行后结果在 `restored/`。
`work/` 是临时处理目录，运行成功后会自动删除。

脚本固定生成的结构名使用英文；从 Claude 导出内容转译出来的项目名、对话名、资料名会保留原文。

## Output layout

```text
restored/
├── README.md
├── memory.md
└── projects/
    └── 项目名/
        ├── memory.md
        ├── references/
        │   └── files/
        └── conversations/
            └── 对话名_2026-01-01_00-00-00_uuid/
                ├── summary.md
                ├── transcript.md
                └── files/
```

## Options

- `--output`: 输出目录。
- `--work-dir`: 临时处理目录。
- `--force`: 重建已存在的输出目录和临时目录。
- `--keep-work-dir`: 保留临时处理目录。
- `--keep-decoded-json`: 保留解码后的 JSON 副本。
- `--min-score`: 分类最低分；低于该分数的对话进入 `未分类对话`。
- `--classification-map`: 使用手动项目归属修正表。

## Classification

脚本会用项目名称、项目文档、项目记忆匹配对话标题和摘要。
如果传入手动修正表，手动修正会优先于自动分类。
低置信度对话会放入 `projects/未分类对话/`，方便后续人工复核。
没有标题、摘要、正文或有效附件名的空对话会自动跳过。
对话中带 `extracted_content` 的附件会写入该对话的 `files/`。
没有记忆、资料、描述和有效对话的空项目会自动跳过。
