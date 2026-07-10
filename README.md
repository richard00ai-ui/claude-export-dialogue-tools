# Claude Export Dialogue Tools

把 Claude 导出的 zip，在浏览器里复核项目归属，并导出成 dialogue-folder 文件夹。

## Files

你只需要这几个文件：

- `classification-reviewer.html`：网页版复核和导出工具。
- `restored.py`：命令行备用脚本。
- `README.md`：使用说明。
- `claude-export.zip`：你从 Claude 导出的数据包，不要上传到 GitHub。

## Web Usage

1. 把 `classification-reviewer.html` 和 `claude-export.zip` 放在同一个文件夹里。
2. 双击打开 `classification-reviewer.html`。
3. 拖入或选择 `claude-export.zip`。
4. 在左侧选择项目，中间选择对话，右侧查看内容。
5. 如果对话归属不对，在右侧下拉框改到正确项目，点击保存归属。
6. 点击 `以文件夹的形式导出`。
7. 选择保存位置，页面会生成一个 `restored-时间戳/` 文件夹。

所有读取、复核和导出都在本地浏览器完成，不需要上传 Claude 数据。

## Web Output

导出的文件夹大致是：

```text
restored-时间戳/
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

`未分类对话` 会作为一个项目文件夹出现。置信分为 0 的对话不会显示，也不会导出。

## Classification Review

页面会自动用项目名称、项目记忆、项目资料和对话内容做初步分类。

复核时重点看：

- 分数低或第一、第二候选接近的对话。
- 被放进 `未分类对话` 的对话。
- 明显属于某个项目、但被分到另一个项目的对话。

修改后的项目归属会直接用于 `以文件夹的形式导出`。

## Optional CLI

如果你不需要网页复核，也可以用脚本直接生成：

```bash
python3 restored.py claude-export.zip --output restored --work-dir work --force
```

常用参数：

- `--output`: 输出目录。
- `--work-dir`: 临时处理目录。
- `--force`: 重建已存在的输出目录和临时目录。
- `--keep-work-dir`: 保留临时处理目录。
- `--keep-decoded-json`: 保留解码后的 JSON 副本。
- `--min-score`: 分类最低分；低于该分数的对话进入 `未分类对话`。
- `--classification-map`: 使用手动项目归属修正表。

## Privacy

不要提交这些文件或目录到 GitHub：

- `claude-export.zip`
- `restored/`
- `restored-*/`
- `work/`
- `.claude-export-work/`
