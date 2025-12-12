#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lang-Monitor: 语言文件更新监控器
监控指定GitHub仓库中的文件变更，并发送邮件通知
"""

import json
import os
import sys
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# GitHub API 基础URL
GITHUB_API_BASE = "https://api.github.com"

def load_json_file(filepath: str) -> dict:
    """加载JSON文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误 {filepath}: {e}")
        return {}

def save_json_file(filepath: str, data: dict) -> None:
    """保存JSON文件"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def github_api_request(endpoint: str, token: Optional[str] = None) -> Tuple[Optional[dict], Optional[str]]:
    """
    发送GitHub API请求
    返回: (数据, 错误信息)
    """
    url = f"{GITHUB_API_BASE}{endpoint}"
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Lang-Monitor'
    }
    
    if token:
        headers['Authorization'] = f'token {token}'
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data, None
    except urllib.error.HTTPError as e:
        error_msg = f"HTTP {e.code}: {e.reason}"
        if e.code == 404:
            error_msg = "仓库或路径不存在"
        elif e.code == 403:
            error_msg = "API请求限制或权限不足"
        return None, error_msg
    except urllib.error.URLError as e:
        return None, f"网络错误: {e.reason}"
    except Exception as e:
        return None, f"未知错误: {str(e)}"

def get_path_commits(repo: str, branch: str, path: str, token: Optional[str] = None) -> Tuple[Optional[List[dict]], Optional[str]]:
    """
    获取指定路径的最新提交
    """
    endpoint = f"/repos/{repo}/commits?sha={branch}&path={path}&per_page=1"
    return github_api_request(endpoint, token)

def get_file_content_sha(repo: str, branch: str, path: str, token: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    获取文件的SHA值（用于检测变更）
    """
    endpoint = f"/repos/{repo}/contents/{path}?ref={branch}"
    data, error = github_api_request(endpoint, token)
    
    if error:
        return None, error
    
    if isinstance(data, list):
        # 如果是目录，计算所有文件SHA的组合哈希
        sha_list = sorted([item.get('sha', '') for item in data])
        combined = hashlib.sha256(''.join(sha_list).encode()).hexdigest()[:40]
        return combined, None
    else:
        return data.get('sha'), None

def generate_monitor_key(monitor: dict, path: str) -> str:
    """生成监控项的唯一键"""
    return f"{monitor['repo']}:{monitor['branch']}:{path}"

def check_for_updates(config: dict, state: dict, token: Optional[str] = None) -> List[dict]:
    """
    检查所有监控项的更新
    返回: 更新列表
    """
    updates = []
    monitors_state = state.get('monitors', {})
    
    for monitor in config.get('monitors', []):
        if not monitor.get('enabled', True):
            print(f"⏭️  跳过已禁用的监控: {monitor.get('name', monitor['repo'])}")
            continue
        
        repo = monitor['repo']
        branch = monitor.get('branch', 'main')
        name = monitor.get('name', repo)
        
        print(f"\n🔍 检查: {name}")
        print(f"   仓库: {repo} (分支: {branch})")
        
        for path in monitor.get('paths', []):
            key = generate_monitor_key(monitor, path)
            print(f"   路径: {path}")
            
            # 获取最新提交
            commits, error = get_path_commits(repo, branch, path, token)
            
            if error:
                print(f"   ❌ 获取提交失败: {error}")
                continue
            
            if not commits:
                print(f"   ⚠️  未找到相关提交")
                continue
            
            latest_commit = commits[0]
            latest_sha = latest_commit['sha']
            commit_message = latest_commit['commit']['message'].split('\n')[0]
            commit_date = latest_commit['commit']['committer']['date']
            commit_author = latest_commit['commit']['author']['name']
            
            # 检查是否有更新
            previous_sha = monitors_state.get(key, {}).get('last_sha')
            
            if previous_sha is None:
                print(f"   📝 首次记录: {latest_sha[:7]}")
                monitors_state[key] = {
                    'last_sha': latest_sha,
                    'last_check': datetime.utcnow().isoformat(),
                    'path': path,
                    'repo': repo,
                    'branch': branch
                }
            elif previous_sha != latest_sha:
                print(f"   🆕 发现更新! {previous_sha[:7]} -> {latest_sha[:7]}")
                
                updates.append({
                    'name': name,
                    'repo': repo,
                    'branch': branch,
                    'path': path,
                    'old_sha': previous_sha,
                    'new_sha': latest_sha,
                    'commit_message': commit_message,
                    'commit_date': commit_date,
                    'commit_author': commit_author,
                    'compare_url': f"https://github.com/{repo}/compare/{previous_sha[:7]}...{latest_sha[:7]}",
                    'commit_url': f"https://github.com/{repo}/commit/{latest_sha}",
                    'file_url': f"https://github.com/{repo}/blob/{branch}/{path}"
                })
                
                monitors_state[key] = {
                    'last_sha': latest_sha,
                    'last_check': datetime.utcnow().isoformat(),
                    'path': path,
                    'repo': repo,
                    'branch': branch
                }
            else:
                print(f"   ✅ 无更新 ({latest_sha[:7]})")
    
    state['monitors'] = monitors_state
    state['last_check'] = datetime.utcnow().isoformat()
    
    return updates

def format_email_content(updates: List[dict], settings: dict) -> Tuple[str, str]:
    """
    格式化邮件内容
    返回: (纯文本内容, HTML内容)
    """
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # 纯文本版本
    text_lines = [
        f"Lang-Monitor 检测到 {len(updates)} 个文件更新",
        f"检查时间: {now}",
        "",
        "=" * 50,
        ""
    ]
    
    # HTML版本
    html_parts = [
        """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }
                h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                .update-card { background: #f8f9fa; border-left: 4px solid #3498db; padding: 15px; margin: 15px 0; border-radius: 0 8px 8px 0; }
                .update-card h3 { margin: 0 0 10px 0; color: #2c3e50; }
                .meta { color: #666; font-size: 0.9em; }
                .commit-msg { background: #fff; padding: 10px; border-radius: 4px; margin: 10px 0; border: 1px solid #ddd; }
                .links a { display: inline-block; margin-right: 15px; color: #3498db; text-decoration: none; }
                .links a:hover { text-decoration: underline; }
                .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.85em; }
            </style>
        </head>
        <body>
        """,
        f"<h1>🔔 Lang-Monitor 更新通知</h1>",
        f"<p>检测到 <strong>{len(updates)}</strong> 个文件更新 | 检查时间: {now}</p>"
    ]
    
    for update in updates:
        # 纯文本
        text_lines.extend([
            f"📦 {update['name']}",
            f"   仓库: {update['repo']}",
            f"   路径: {update['path']}",
            f"   分支: {update['branch']}",
            f"   作者: {update['commit_author']}",
            f"   时间: {update['commit_date']}",
        ])
        
        if settings.get('include_commit_message', True):
            text_lines.append(f"   提交: {update['commit_message']}")
        
        if settings.get('include_diff_link', True):
            text_lines.extend([
                f"   对比: {update['compare_url']}",
                f"   提交: {update['commit_url']}",
                f"   文件: {update['file_url']}"
            ])
        
        text_lines.extend(["", "-" * 50, ""])
        
        # HTML
        html_parts.append(f"""
        <div class="update-card">
            <h3>📦 {update['name']}</h3>
            <div class="meta">
                <p><strong>仓库:</strong> {update['repo']} | <strong>分支:</strong> {update['branch']}</p>
                <p><strong>路径:</strong> <code>{update['path']}</code></p>
                <p><strong>作者:</strong> {update['commit_author']} | <strong>时间:</strong> {update['commit_date']}</p>
            </div>
        """)
        
        if settings.get('include_commit_message', True):
            html_parts.append(f"""
            <div class="commit-msg">
                <strong>提交信息:</strong> {update['commit_message']}
            </div>
            """)
        
        if settings.get('include_diff_link', True):
            html_parts.append(f"""
            <div class="links">
                <a href="{update['compare_url']}">📊 查看对比</a>
                <a href="{update['commit_url']}">📝 查看提交</a>
                <a href="{update['file_url']}">📄 查看文件</a>
            </div>
            """)
        
        html_parts.append("</div>")
    
    html_parts.append("""
        <div class="footer">
            <p>此邮件由 <a href="https://github.com/nageih/Lang-Monitor">Lang-Monitor</a> 自动发送</p>
            <p>如需修改监控配置，请编辑仓库中的 <code>config/monitors.json</code> 文件</p>
        </div>
        </body>
        </html>
    """)
    
    return '\n'.join(text_lines), ''.join(html_parts)

def send_email(updates: List[dict], settings: dict) -> bool:
    """
    发送邮件通知
    需要设置环境变量:
    - EMAIL_SMTP_SERVER: SMTP服务器地址
    - EMAIL_SMTP_PORT: SMTP端口
    - EMAIL_USERNAME: 邮箱账号
    - EMAIL_PASSWORD: 邮箱密码/授权码
    - EMAIL_TO: 收件人邮箱
    """
    smtp_server = os.environ.get('EMAIL_SMTP_SERVER')
    smtp_port = int(os.environ.get('EMAIL_SMTP_PORT', '587'))
    username = os.environ.get('EMAIL_USERNAME')
    password = os.environ.get('EMAIL_PASSWORD')
    to_email = os.environ.get('EMAIL_TO')
    
    if not all([smtp_server, username, password, to_email]):
        print("❌ 邮件配置不完整，请检查环境变量")
        print("   需要: EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_TO")
        return False
    
    prefix = settings.get('email_subject_prefix', '[Lang-Monitor]')
    subject = f"{prefix} 检测到 {len(updates)} 个翻译文件更新"
    
    text_content, html_content = format_email_content(updates, settings)
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = username
    msg['To'] = to_email
    
    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    try:
        print(f"\n📧 发送邮件到: {to_email}")
        
        if smtp_port == 465:
            # SSL连接
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
        else:
            # TLS连接
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.starttls()
        
        server.login(username, password)
        server.sendmail(username, [to_email], msg.as_string())
        server.quit()
        
        print("✅ 邮件发送成功!")
        return True
        
    except smtplib.SMTPException as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 50)
    print("🔍 Lang-Monitor - 翻译文件更新监控器")
    print("=" * 50)
    
    # 获取脚本所在目录的父目录作为项目根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    
    config_path = os.path.join(root_dir, 'config', 'monitors.json')
    state_path = os.path.join(root_dir, 'data', 'state.json')
    
    # 加载配置和状态
    config = load_json_file(config_path)
    state = load_json_file(state_path)
    
    if not config.get('monitors'):
        print("❌ 未找到监控配置，请编辑 config/monitors.json")
        sys.exit(1)
    
    settings = config.get('settings', {})
    
    # 获取GitHub Token（可选，但推荐使用以提高API限制）
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        print("⚠️  未设置 GITHUB_TOKEN，API请求可能受限")
    
    # 检查更新
    updates = check_for_updates(config, state, github_token)
    
    # 保存状态
    save_json_file(state_path, state)
    print(f"\n💾 状态已保存到: {state_path}")
    
    # 输出结果摘要
    print("\n" + "=" * 50)
    if updates:
        print(f"📢 发现 {len(updates)} 个更新!")
        
        # 发送邮件
        if os.environ.get('EMAIL_SMTP_SERVER'):
            send_email(updates, settings)
        else:
            print("⚠️  未配置邮件，跳过邮件发送")
            print("   设置 EMAIL_* 环境变量以启用邮件通知")
        
        # 设置GitHub Actions输出
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output:
            with open(github_output, 'a') as f:
                f.write(f"has_updates=true\n")
                f.write(f"update_count={len(updates)}\n")
        
        # 输出更新详情（用于Actions日志）
        print("\n📋 更新详情:")
        for update in updates:
            print(f"  - {update['name']}: {update['path']}")
            print(f"    {update['commit_message']}")
    else:
        print("✅ 所有监控项均无更新")
        
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output:
            with open(github_output, 'a') as f:
                f.write("has_updates=false\n")
                f.write("update_count=0\n")
    
    print("=" * 50)
    
    return 0 if not updates else 0  # 有更新也返回0，避免CI失败

if __name__ == '__main__':
    sys.exit(main())
