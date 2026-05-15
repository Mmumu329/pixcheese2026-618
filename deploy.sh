#!/usr/bin/env bash
# 一键部署看板到 GitHub Pages
# 前置：已执行 gh auth login 完成登录

set -e

REPO_NAME="pixcheese2026-618"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE"

echo "================================================"
echo "  像素芝士大促数据看板 · 一键部署到 GitHub Pages"
echo "================================================"
echo ""

# 1. 检查 gh 登录
if ! gh auth status &>/dev/null; then
  echo "❌ 未登录 GitHub，请先执行：gh auth login -h github.com -p https --web"
  exit 1
fi

GH_USER=$(gh api user --jq .login)
echo "✅ 已登录 GitHub 账号: $GH_USER"
echo ""

# 2. 配置 git
if [ -z "$(git config --global user.email)" ]; then
  git config --global user.email "${GH_USER}@users.noreply.github.com"
fi
if [ -z "$(git config --global user.name)" ]; then
  git config --global user.name "$GH_USER"
fi

# 3. 创建 Repo（如果不存在）
if gh repo view "$GH_USER/$REPO_NAME" &>/dev/null; then
  echo "ℹ️  Repo $GH_USER/$REPO_NAME 已存在，跳过创建"
else
  echo "📦 创建 Repo: $GH_USER/$REPO_NAME"
  gh repo create "$REPO_NAME" --public --description "像素芝士大促数据看板" --confirm 2>/dev/null || \
    gh repo create "$REPO_NAME" --public --description "像素芝士大促数据看板"
fi

# 4. 初始化本地 git 仓库
if [ ! -d .git ]; then
  echo "📁 初始化本地 git..."
  git init -b main
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GH_USER}/${REPO_NAME}.git"

# 5. 提交并 push
git add .
if git diff --cached --quiet; then
  echo "ℹ️  无新增文件"
else
  git commit -m "deploy: 看板首次部署 $(date +%Y-%m-%d_%H:%M:%S)"
fi

echo "📤 推送代码..."
git push -u origin main --force

# 6. 开启 GitHub Pages（用 Actions 作为 source）
echo "🌐 开启 GitHub Pages（Source: GitHub Actions）..."
gh api -X POST "repos/$GH_USER/$REPO_NAME/pages" \
  -f "build_type=workflow" 2>/dev/null || \
gh api -X PUT "repos/$GH_USER/$REPO_NAME/pages" \
  -f "build_type=workflow" 2>/dev/null || \
  echo "  (如已开启会失败，正常忽略)"

# 7. 触发 Workflow
echo "🚀 触发首次部署 Workflow..."
sleep 2
gh workflow run "update.yml" --repo "$GH_USER/$REPO_NAME" 2>/dev/null || \
  echo "  (Workflow 会在 push 后自动按计划运行)"

echo ""
echo "================================================"
echo "✅ 部署完成！"
echo "================================================"
echo ""
echo "📍 Repo:     https://github.com/$GH_USER/$REPO_NAME"
echo "🌐 看板 URL: https://${GH_USER,,}.github.io/${REPO_NAME}/"
echo ""
echo "首次部署需要 1-3 分钟，可以在 Actions 页面查看进度："
echo "   https://github.com/$GH_USER/$REPO_NAME/actions"
echo ""
echo "本机定时任务会从 Metabase 拉最新数据并推送部署，"
echo "把上面这个看板 URL 收藏到浏览器或分享给团队即可。"
