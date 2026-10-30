---
name: 来源坏了 / Source broken
about: 某个刮削来源不再返回资料、封面或头像
title: '[来源] '
labels: source
assignees: ''
---

## 哪个来源、哪个番号

- 来源名（`r18dev dmm 1pondo fc2 javarchive javdb javbus avbase` 之一）：
- 番号：
- `shelf --version`：

## 冒烟输出

本机跑一遍真实冒烟，把完整输出贴在下面：

```bash
uv run python scripts/smoke_sources.py <番号> --sources <来源名>
```

```
```

## Cookie

- [ ] 这个来源在全局配置里配了 Cookie
- [ ] 没配

**不要贴 Cookie 值**，也不要贴 `~/.hidden-shelf/config.json` 的内容。只说有没有。

## 其它

浏览器里直接打开这个番号的页面能看到资料吗？站方最近有没有改版、加验证？
