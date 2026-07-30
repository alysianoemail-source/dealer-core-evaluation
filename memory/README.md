# 记忆存储

> version: v0.1
> 规则：Append-only，不覆盖，软删除

---

## 命名规则

- 企业判定记录：`{企业名}_判定记录.md`（企业名中的 `/` 替换为 `_`）
- 批次记录：`batch_{batch_id}.md`
- 索引文件：`index.json`（维护所有记忆记录的最新版本指针）

## 文件结构

```
memory/
├── README.md          ← 本文件
├── index.json         ← 记忆索引（维护最新版本指针）
├── records/           ← 企业判定记录
│   ├── 华曜智能终端有限公司_判定记录.md
│   └── ...
├── batches/           ← 批次记录
│   └── batch_B20260723_001.md
└── reviews/           ← 复核记录
    └── ...
```

## 操作规则

| 操作 | 规则 |
|------|------|
| 写入 | Append-only，每条记录含 created_at/created_by/version |
| 更新 | 标记旧版本 superseded_by，写入新版本 |
| 删除 | 仅软删除（deleted_at + deleted_reason） |
| 查询 | 默认查最新 + 未删除；--history 看全版本；--include-deleted 看已删 |
