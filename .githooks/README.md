# Git Hooks（模板）

本仓库提供 `.githooks/pre-commit`，用于在本地提交前自动检查/补齐源代码文件 SPDX 许可证头。

启用方式：

```bash
git config core.hooksPath .githooks
```

验证方式：

1) 新建一个源代码文件（例如 `src/foo.py`），不写 SPDX 头
2) `git add src/foo.py`
3) `git commit -m "test"`
4) pre-commit 会自动插入 SPDX 头并重新 `git add`
