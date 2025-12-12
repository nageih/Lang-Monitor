# Lang-Monitor 🔍

自动监控 GitHub 仓库中翻译文件的更新，并通过邮件发送通知。

## ✨ 功能特点

- 📁 **批量监控**: 同时监控多个仓库中的多个文件/文件夹
- 🔔 **邮件通知**: 检测到更新时自动发送格式化的邮件通知
- ⏰ **定时检查**: 通过 GitHub Actions 定时自动运行
- 🔗 **便捷链接**: 邮件中包含文件对比、提交详情等快捷链接
- 💾 **状态持久化**: 自动记录检查状态，避免重复通知
- 🆓 **完全免费**: 利用 GitHub Actions 免费额度运行

## 📁 项目结构

```
Lang-Monitor/
├── .github/
│   └── workflows/
│       └── check-updates.yml    # GitHub Actions 工作流
├── config/
│   └── monitors.json            # 监控配置文件
├── data/
│   └── state.json               # 状态记录文件（自动更新）
├── scripts/
│   └── check_updates.py         # 核心检查脚本
└── README.md
```

## 🚀 快速开始

### 1. Fork 本仓库

点击右上角的 Fork 按钮，将本仓库复制到你的账号下。

### 2. 配置监控目标

编辑 `config/monitors.json` 文件，添加你要监控的仓库和文件：

```json
{
  "monitors": [
    {
      "name": "我的模组翻译",
      "repo": "SomeAuthor/SomeMod",
      "branch": "main",
      "paths": [
        "src/main/resources/assets/modid/lang/en_us.json",
        "src/main/resources/assets/modid/lang/"
      ],
      "enabled": true
    },
    {
      "name": "另一个项目",
      "repo": "AnotherAuthor/AnotherRepo",
      "branch": "master",
      "paths": [
        "locales/en.json"
      ],
      "enabled": true
    }
  ],
  "settings": {
    "check_interval_hours": 6,
    "email_subject_prefix": "[Lang-Monitor]",
    "include_diff_link": true,
    "include_commit_message": true
  }
}
```

#### 配置说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 监控项名称（用于显示） | `"Minecraft模组翻译"` |
| `repo` | 仓库路径 (owner/repo) | `"MinecraftForge/MinecraftForge"` |
| `branch` | 要监控的分支 | `"main"` 或 `"master"` |
| `paths` | 要监控的文件或文件夹路径列表 | `["lang/en_us.json", "i18n/"]` |
| `enabled` | 是否启用此监控项 | `true` 或 `false` |

### 3. 配置邮件通知

在仓库的 Settings → Secrets and variables → Actions 中添加以下 Secrets：

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `EMAIL_SMTP_SERVER` | SMTP 服务器地址 | `smtp.gmail.com` |
| `EMAIL_SMTP_PORT` | SMTP 端口 | `587`（TLS）或 `465`（SSL） |
| `EMAIL_USERNAME` | 发件邮箱地址 | `your-email@gmail.com` |
| `EMAIL_PASSWORD` | 邮箱密码或应用专用密码 | `your-app-password` |
| `EMAIL_TO` | 收件人邮箱地址 | `notify@example.com` |

#### 常用邮箱 SMTP 配置

<details>
<summary>📧 Gmail</summary>

- SMTP 服务器: `smtp.gmail.com`
- 端口: `587`（TLS）或 `465`（SSL）
- 需要开启"允许不够安全的应用"或使用[应用专用密码](https://support.google.com/accounts/answer/185833)

</details>

<details>
<summary>📧 QQ 邮箱</summary>

- SMTP 服务器: `smtp.qq.com`
- 端口: `587`（TLS）或 `465`（SSL）
- 需要在邮箱设置中开启 SMTP 服务并获取授权码

</details>

<details>
<summary>📧 163 邮箱</summary>

- SMTP 服务器: `smtp.163.com`
- 端口: `25` 或 `465`（SSL）
- 需要在邮箱设置中开启 SMTP 服务并获取授权码

</details>

<details>
<summary>📧 Outlook/Hotmail</summary>

- SMTP 服务器: `smtp-mail.outlook.com`
- 端口: `587`（TLS）

</details>

### 4. 启用 GitHub Actions

1. 进入仓库的 Actions 标签页
2. 如果看到提示，点击 "I understand my workflows, go ahead and enable them"
3. 工作流将按照配置的时间自动运行

### 5. 手动测试

你也可以手动触发工作流来测试：

1. 进入 Actions 标签页
2. 选择 "Lang Monitor - 翻译文件更新检查"
3. 点击 "Run workflow"
4. 点击绿色的 "Run workflow" 按钮

## 📧 邮件通知示例

当检测到更新时，你会收到类似这样的邮件：

```
📦 我的模组翻译
   仓库: SomeAuthor/SomeMod
   路径: src/main/resources/assets/modid/lang/en_us.json
   分支: main
   作者: contributor
   时间: 2024-01-15T10:30:00Z
   提交: Add new translations for v1.2.0

   📊 查看对比 | 📝 查看提交 | 📄 查看文件
```

## ⚙️ 高级配置

### 修改检查频率

编辑 `.github/workflows/check-updates.yml` 中的 cron 表达式：

```yaml
schedule:
  # 每小时检查一次
  - cron: '0 * * * *'
  
  # 每天早上8点检查（UTC时间）
  - cron: '0 8 * * *'
  
  # 每6小时检查一次（默认）
  - cron: '0 */6 * * *'
```

### 监控整个文件夹

路径以 `/` 结尾时会监控整个文件夹的变更：

```json
{
  "paths": [
    "src/main/resources/assets/modid/lang/"
  ]
}
```

### 禁用某个监控项

将 `enabled` 设置为 `false`：

```json
{
  "name": "暂时不监控的项目",
  "enabled": false,
  ...
}
```

## 🔧 故障排除

### 常见问题

**Q: Actions 运行失败，显示 API 请求限制**

A: 未认证的 GitHub API 请求有速率限制。确保在 Actions 中使用了 `GITHUB_TOKEN`。

**Q: 邮件发送失败**

A: 请检查：
1. 所有邮件相关的 Secrets 是否正确设置
2. 邮箱是否开启了 SMTP 服务
3. 是否使用了正确的密码/授权码

**Q: 没有收到邮件但 Actions 显示成功**

A: 检查邮件是否被归类到垃圾邮件文件夹。

**Q: 首次运行没有发送邮件**

A: 首次运行会记录当前状态作为基准，只有后续检测到变更才会发送通知。

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
