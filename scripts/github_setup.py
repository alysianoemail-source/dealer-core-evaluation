"""GitHub 仓库创建 + git push (HTTPS + Token)"""
import subprocess, sys, json, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("GITHUB_TOKEN", "") or input("请输入 GitHub Personal Access Token: ").strip()
REPO_NAME = "dealer-core-evaluation"
USER = "alysianoemail-source"
REMOTE = f"https://{USER}:{TOKEN}@github.com/{USER}/{REPO_NAME}.git"

def run(cmd, cwd=ROOT):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.returncode and r.stderr:
        print(f"    stderr: {r.stderr[:200]}")
    return r.stdout.strip()

# Step 1: Create repo via API
print("[1/4] 在 GitHub 创建仓库...")
req = urllib.request.Request(
    "https://api.github.com/user/repos",
    data=json.dumps({"name": REPO_NAME, "private": False}).encode(),
    headers={
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    })
try:
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    print(f"  -> {data['html_url']}")
except urllib.request.HTTPError as e:
    err = json.loads(e.read())
    if err.get("message") == "Repository creation failed." and "name already exists" in str(err):
        print(f"  -> 仓库已存在，跳过")
    else:
        print(f"  -> 错误: {err.get('message', e)}")
        sys.exit(1)

# Step 2: Add remote
print("[2/4] 添加 git remote...")
out = run(f"git remote add origin {REMOTE}")
if "already exists" in out:
    run(f"git remote set-url origin {REMOTE}")

# Step 3: Add & commit
print("[3/4] git add + commit...")
run("git add -A")
status = run("git status --short")
if status:
    run('git commit -m "v1.0 MVP: 评分引擎 + API + 前端演示"')
    print(f"  -> 提交了 {len(status.splitlines())} 个文件")
else:
    print("  -> 无变更需提交")

# Step 4: Push to main
print("[4/4] 推送到 GitHub...")
out = run("git push -u origin main")
print(f"  -> {out[:150] if out else '推送成功'}")
print(f"\n✅ 完成！仓库地址：https://github.com/{USER}/{REPO_NAME}")
