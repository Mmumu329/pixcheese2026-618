# 像素芝士大促数据看板 · 部署说明

公网可访问 · 30 分钟自动刷新 · 完全免费

---

## 一图看懂部署架构

```
┌──────────────────────────┐
│  Metabase                │
│  metabase.pixcakeai.com  │   ←─── 数据真源（公司内）
└────────────┬─────────────┘
             │ API (Session 登录)
             ▼
┌──────────────────────────┐
│  GitHub Actions          │
│  每 30 分钟跑 update_data│   ←─── 自动化拉数据
│  生成 dashboard_data.json│
│  自动提交回 Repo         │
└────────────┬─────────────┘
             │ git push
             ▼
┌──────────────────────────┐
│  GitHub Pages            │
│  https://你的用户名.     │   ←─── 外网访问点
│  github.io/项目名/       │       (公网可访问、免登录)
└────────────┬─────────────┘
             │
             ▼
       打开 URL → 看板自动加载最新数据
```

---

## 一次性部署（10 分钟搞定）

### 步骤 1：注册 GitHub 账号（已有就跳过）

打开 https://github.com/signup ，注册账号。

### 步骤 2：创建一个新 Repo（仓库）

1. 登录后右上角点 **+** → **New repository**
2. 填名字，**建议用一个不容易被猜到的名字**，比如：`pix-d-2026-x9k2m7`
3. 选 **Public**（GitHub Pages 免费版只支持 Public Repo；Repo 名足够随机就够安全了）
4. 点 **Create repository**

### 步骤 3：上传文件到 Repo

打开 Terminal，把当前 `像素芝士大促看板部署/` 整个目录推上去：

```bash
cd /Users/mumuu/Desktop/像素芝士大促看板部署
git init -b main
git add .
git commit -m "init: dashboard deploy"
git remote add origin https://github.com/<你的用户名>/<你的Repo名>.git
git push -u origin main
```

> 如果是第一次用 git，会提示输 GitHub 密码。
> 现在密码登录已废弃，需要用 **Personal Access Token (PAT)**：
> https://github.com/settings/tokens → Generate new token → 勾选 `repo` 权限 → 复制 token 当密码用

### 步骤 4：配置 Metabase 凭据（Secrets）

打开你刚建的 Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

需要添加 3 个：

| 名称 | 值 |
|------|----|
| `METABASE_URL` | `https://metabase.pixcakeai.com` |
| `METABASE_USER` | `jbr@pixcakeai.com` |
| `METABASE_PASS` | `jdsiT9QmzPzuzp` |

> Secrets 是加密存储的，连 Repo 的协作者都看不到原文，只有 Actions 跑的时候才会注入。

### 步骤 5：开启 GitHub Pages

打开 Repo → **Settings** → **Pages**

- **Source** 选 `GitHub Actions`（不要选 `Deploy from a branch`）
- 保存

### 步骤 6：手动触发一次 Workflow（测试）

打开 Repo → **Actions** → 左侧选 `Update Dashboard Data` → 右上 **Run workflow** 按钮 → 确认运行。

等 1-2 分钟，看到绿勾就 ✅。

### 步骤 7：访问看板

部署成功后，你的看板 URL 会是：

```
https://<你的用户名>.github.io/<你的Repo名>/
```

例如：
```
https://yourname.github.io/pix-d-2026-x9k2m7/
```

**把这个 URL 收藏到浏览器书签 / 分享给团队，以后每次打开都是最新数据。**

---

## 数据多久更新一次？

- GitHub Actions 每 **30 分钟** 自动跑一次（cron 表达式 `*/30 * * * *`）
- 看板打开后，**每 10 分钟也会自动 fetch 一次 dashboard_data.json**
- 也可以点看板右上角 **⟳ 刷新数据** 按钮立即刷新

如果想改频率，修改 `.github/workflows/update.yml` 第 6 行：

```yaml
- cron: '*/10 * * * *'  # 每 10 分钟
- cron: '0 * * * *'     # 每小时整点
- cron: '*/5 * * * *'   # 每 5 分钟（注意 GitHub 免费额度每月 2000 分钟）
```

---

## 想加一道弱保护？

GitHub Pages 免费版没法加密码。如果担心 URL 泄露，三个建议：

### 方案 1（最简单）：用极长随机 Repo 名
比如 `pix-dashboard-x9k2m7-q4r8p1` —— 没有这个完整名字猜不到。

### 方案 2（推荐）：用 Cloudflare 代理 + Basic Auth
1. 把域名转入 Cloudflare（免费）
2. 在 Cloudflare 加 **Cloudflare Access**（5 用户内免费）
3. 设邮箱白名单，访问时输公司邮箱发的验证码
4. 团队成员一次登录后浏览器记住 24h，体验无感

### 方案 3：换 Vercel + Password Protection
Vercel Pro $20/月，可以一键给静态站加密码。

---

## 替代部署方式

如果不想用 GitHub Pages，可以选：

### A. Vercel（也免费）
1. 注册 https://vercel.com/
2. Import GitHub Repo
3. 加 Environment Variables（同 Secrets）
4. 部署完得到 `https://你的项目.vercel.app/`
5. 但 Vercel 不会自动跑 cron — 需要用 Vercel Cron Jobs（Pro 才有）或换成 GitHub Actions 跑数据 + Vercel 跑前端

### B. Cloudflare Pages
- 类似 Vercel，免费、CDN 全球加速、国内访问也快
- 部署流程几乎和 GitHub Pages 一样

### C. 公司云服务器
- 把这些文件丢到 `/var/www/dashboard/`
- nginx 静态服务
- 加 crontab 跑 `update_data.py`
- 优点：可以加 IP 白名单 / 内网访问

---

## 本地测试

不想等 GitHub Actions 跑，先在本地试一下：

```bash
cd /Users/mumuu/Desktop/像素芝士大促看板部署

# 设环境变量
export METABASE_URL=https://metabase.pixcakeai.com
export METABASE_USER=jbr@pixcakeai.com
export METABASE_PASS='jdsiT9QmzPzuzp'

# 跑脚本，会更新 dashboard_data.json
python scripts/update_data.py

# 打开 index.html 看效果
open index.html
```

---

## 安全提示

⚠️ **千万不要** 把 `METABASE_PASS` 直接写到代码里 commit 上去。  
- 代码里只读 `os.environ`，凭据存在 GitHub Secrets
- 即使 Repo 是 Public，Secrets 也不会泄露
- 如果不小心把密码 commit 了，**立即在 Metabase 修改密码**

⚠️ **数据敏感性**：看板包含 GMV、订单数等业务数据，建议至少做到方案 1（极长随机 Repo 名）。  

---

## 常见问题

### Q1: Actions 失败提示登录错误？
检查 Secrets 是否拼对。注意 `METABASE_PASS` 末尾没有空格。

### Q2: 看板打开后还是旧数据？
- 看 Actions 是否正常跑完（绿勾）
- 浏览器 Hard Refresh（Cmd+Shift+R）
- 点看板右上「⟳ 刷新数据」

### Q3: 想给团队多个人看，他们改不改得了数据？
不能改。看板是只读的，数据由 Metabase → Actions → JSON 单向流动。

### Q4: 5/13 之前埋点数据是空的，看板会报错吗？
不会。脚本里对事件数据为空有兜底，会跳过事件聚合，订单数据照常更新。

### Q5: 想加更多页签 / 修改样式？
直接改 `index.html`，commit 推上去，GitHub Pages 几分钟内会重新部署。

---

## 文件结构

```
像素芝士大促看板部署/
├── index.html             # 看板（核心 UI）
├── dashboard_data.json    # 数据快照（自动更新）
├── scripts/
│   └── update_data.py     # 数据拉取 + 聚合脚本
├── .github/
│   └── workflows/
│       └── update.yml     # GitHub Actions 配置
├── .gitignore
└── README.md
```

---

部署完后，把 URL 收藏到浏览器 / 钉钉群置顶 / 分享链接给老板，每次打开都是最新数据。
