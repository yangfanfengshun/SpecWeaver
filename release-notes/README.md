# SpecWeaver 版本说明

每个正式版本使用独立文件：

```text
vX.Y.Z.md
```

版本说明会原样用于对应 GitHub Release，必须只包含可公开信息。不得复制含私有
仓库地址、Tower 任务链接、Cookie、密码、Token、内部账号或内部验证数据的内容。

模板：

```markdown
# SpecWeaver vX.Y.Z

## 本次更新

- <面向用户的新增或优化>

## 问题修复

- <面向用户的问题修复；没有则删除本节>

## 验证结果

- <自动化测试和必要的公开验证结论>
```

发布前删除所有占位文字，并运行：

```bash
python3 scripts/check-release.py
```

这里的命令从开发仓库根目录执行。
