#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lang-Monitor: 语言文件更新监控器
监控指定GitHub仓库中的文件变更，并发送邮件通知
支持 Microsoft To Do 集成
"""

import json
import os
import sys
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# API 基础URL
GITHUB_API_BASE = "https://api.github.com"
MS_GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MS_LOGIN_BASE = "https://login.microsoftonline.com"

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
    格式化邮件内容 - 美化版本
    返回: (纯文本内容, HTML内容)
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # 按仓库分组更新
    updates_by_repo = {}
    for update in updates:
        repo = update['repo']
        if repo not in updates_by_repo:
            updates_by_repo[repo] = []
        updates_by_repo[repo].append(update)
    
    repo_count = len(updates_by_repo)
    file_count = len(updates)
    
    # 纯文本版本
    text_lines = [
        "━" * 50,
        f"📢 Lang-Monitor 翻译文件更新通知",
        "━" * 50,
        "",
        f"⏰ 检查时间: {now}",
        f"📊 更新概览: {repo_count} 个仓库 / {file_count} 个文件",
        "",
        "━" * 50,
        ""
    ]
    
    for repo, repo_updates in updates_by_repo.items():
        text_lines.append(f"📦 仓库: {repo}")
        text_lines.append("-" * 40)
        
        for update in repo_updates:
            text_lines.extend([
                f"  📄 {update['path']}",
                f"     监控名: {update['name']}",
                f"     作者: {update['commit_author']}",
                f"     时间: {update['commit_date']}",
            ])
            
            if settings.get('include_commit_message', True):
                text_lines.append(f"     提交: {update['commit_message']}")
            
            if settings.get('include_diff_link', True):
                text_lines.extend([
                    f"     🔗 对比: {update['compare_url']}",
                    f"     🔗 提交: {update['commit_url']}"
                ])
            text_lines.append("")
        text_lines.append("")
    
    text_lines.extend([
        "━" * 50,
        "此邮件由 Lang-Monitor 自动发送",
        "https://github.com/nageih/Lang-Monitor"
    ])
    
    # HTML版本 - 现代化设计
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Lang-Monitor 更新通知</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="min-width: 320px;">
            <tr>
                <td align="center" style="padding: 40px 20px;">
                    <table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 16px; box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);">
                        <!-- Header -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 32px 40px; border-radius: 16px 16px 0 0;">
                                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                    <tr>
                                        <td>
                                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">
                                                🔔 翻译文件更新通知
                                            </h1>
                                            <p style="margin: 8px 0 0 0; color: rgba(255, 255, 255, 0.9); font-size: 14px;">
                                                Lang-Monitor 自动检测
                                            </p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                        <!-- Stats Banner -->
                        <tr>
                            <td style="padding: 0 40px;">
                                <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%); border-radius: 12px; margin-top: -20px; position: relative;">
                                    <tr>
                                        <td style="padding: 20px;" align="center">
                                            <table cellpadding="0" cellspacing="0" border="0">
                                                <tr>
                                                    <td style="padding: 0 30px; text-align: center;">
                                                        <div style="font-size: 32px; font-weight: 700; color: #667eea;">{repo_count}</div>
                                                        <div style="font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px;">仓库</div>
                                                    </td>
                                                    <td style="width: 1px; background-color: #ddd; height: 40px;"></td>
                                                    <td style="padding: 0 30px; text-align: center;">
                                                        <div style="font-size: 32px; font-weight: 700; color: #764ba2;">{file_count}</div>
                                                        <div style="font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px;">文件更新</div>
                                                    </td>
                                                </tr>
                                            </table>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                        <!-- Time Info -->
                        <tr>
                            <td style="padding: 20px 40px 10px 40px;">
                                <p style="margin: 0; color: #888; font-size: 13px;">
                                    ⏰ 检查时间: {now}
                                </p>
                            </td>
                        </tr>
                        
                        <!-- Updates Content -->
                        <tr>
                            <td style="padding: 10px 40px 30px 40px;">
    """
    
    for repo, repo_updates in updates_by_repo.items():
        html_content += f"""
                                <!-- Repository Section -->
                                <div style="margin-bottom: 24px;">
                                    <div style="display: flex; align-items: center; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #f0f2f5;">
                                        <span style="font-size: 20px; margin-right: 10px;">📦</span>
                                        <span style="font-size: 16px; font-weight: 600; color: #333;">{repo}</span>
                                    </div>
        """
        
        for update in repo_updates:
            commit_msg_html = ""
            if settings.get('include_commit_message', True):
                commit_msg_html = f"""
                                        <div style="background-color: #f8f9fa; padding: 12px 16px; border-radius: 8px; margin: 12px 0; border-left: 3px solid #667eea;">
                                            <span style="color: #666; font-size: 12px;">💬 提交信息</span><br>
                                            <span style="color: #333; font-size: 14px;">{update['commit_message']}</span>
                                        </div>
                """
            
            links_html = ""
            if settings.get('include_diff_link', True):
                links_html = f"""
                                        <div style="margin-top: 16px;">
                                            <a href="{update['compare_url']}" style="display: inline-block; padding: 8px 16px; background-color: #667eea; color: white; text-decoration: none; border-radius: 6px; font-size: 13px; margin-right: 8px; margin-bottom: 8px;">📊 查看对比</a>
                                            <a href="{update['commit_url']}" style="display: inline-block; padding: 8px 16px; background-color: #764ba2; color: white; text-decoration: none; border-radius: 6px; font-size: 13px; margin-right: 8px; margin-bottom: 8px;">📝 查看提交</a>
                                            <a href="{update['file_url']}" style="display: inline-block; padding: 8px 16px; background-color: #28a745; color: white; text-decoration: none; border-radius: 6px; font-size: 13px; margin-bottom: 8px;">📄 查看文件</a>
                                        </div>
                """
            
            html_content += f"""
                                    <div style="background-color: #ffffff; border: 1px solid #e8e8e8; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);">
                                        <div style="display: flex; align-items: flex-start; margin-bottom: 12px;">
                                            <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 500;">{update['name']}</span>
                                        </div>
                                        
                                        <div style="font-family: 'SF Mono', Consolas, monospace; font-size: 14px; color: #333; background-color: #f6f8fa; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; word-break: break-all;">
                                            {update['path']}
                                        </div>
                                        
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="font-size: 13px; color: #666;">
                                            <tr>
                                                <td style="padding: 4px 0;">
                                                    <span style="color: #999;">👤 作者:</span> <span style="color: #333;">{update['commit_author']}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 4px 0;">
                                                    <span style="color: #999;">🕐 时间:</span> <span style="color: #333;">{update['commit_date']}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 4px 0;">
                                                    <span style="color: #999;">🔀 分支:</span> <span style="color: #333;">{update['branch']}</span>
                                                </td>
                                            </tr>
                                        </table>
                                        
                                        {commit_msg_html}
                                        {links_html}
                                    </div>
            """
        
        html_content += """
                                </div>
        """
    
    html_content += """
                            </td>
                        </tr>
                        
                        <!-- Footer -->
                        <tr>
                            <td style="background-color: #f8f9fa; padding: 24px 40px; border-radius: 0 0 16px 16px; border-top: 1px solid #e8e8e8;">
                                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                    <tr>
                                        <td>
                                            <p style="margin: 0 0 8px 0; color: #666; font-size: 13px;">
                                                此邮件由 <a href="https://github.com/nageih/Lang-Monitor" style="color: #667eea; text-decoration: none; font-weight: 500;">Lang-Monitor</a> 自动发送
                                            </p>
                                            <p style="margin: 0; color: #999; font-size: 12px;">
                                                如需修改监控配置，请编辑仓库中的 <code style="background-color: #e8e8e8; padding: 2px 6px; border-radius: 4px; font-size: 11px;">config/monitors.json</code> 文件
                                            </p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    return '\n'.join(text_lines), html_content

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
    
    # 生成更美观的邮件标题
    repo_count = len(set(u['repo'] for u in updates))
    if repo_count == 1:
        repo_name = updates[0]['repo'].split('/')[-1]
        subject = f"{prefix} 📢 {repo_name} 有 {len(updates)} 个文件更新"
    else:
        subject = f"{prefix} 📢 {repo_count} 个仓库共 {len(updates)} 个文件更新"
    
    text_content, html_content = format_email_content(updates, settings)
    
    # 设置发件人显示名称
    from email.utils import formataddr
    sender_name = settings.get('email_sender_name', 'Lang-Monitor')
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = formataddr((sender_name, username))
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


# ============================================================
# Microsoft To Do 集成
# ============================================================

def get_ms_access_token() -> Optional[str]:
    """
    获取 Microsoft Graph API 访问令牌
    使用 Client Credentials 流程（需要 Azure AD 应用）
    
    需要环境变量:
    - MS_TODO_TENANT_ID: Azure AD 租户ID
    - MS_TODO_CLIENT_ID: 应用程序(客户端)ID
    - MS_TODO_CLIENT_SECRET: 客户端密码
    
    或者直接使用:
    - MS_TODO_REFRESH_TOKEN: 刷新令牌（用于个人账户）
    """
    # 方式1: 使用刷新令牌（推荐用于个人微软账户）
    refresh_token = os.environ.get('MS_TODO_REFRESH_TOKEN')
    client_id = os.environ.get('MS_TODO_CLIENT_ID')
    
    if refresh_token and client_id:
        return refresh_access_token(client_id, refresh_token)
    
    # 方式2: 使用客户端凭证（适用于组织账户）
    tenant_id = os.environ.get('MS_TODO_TENANT_ID')
    client_secret = os.environ.get('MS_TODO_CLIENT_SECRET')
    
    if all([tenant_id, client_id, client_secret]):
        return get_client_credentials_token(tenant_id, client_id, client_secret)
    
    return None


def refresh_access_token(client_id: str, refresh_token: str) -> Optional[str]:
    """使用刷新令牌获取新的访问令牌"""
    url = f"{MS_LOGIN_BASE}/common/oauth2/v2.0/token"
    
    data = {
        'client_id': client_id,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': 'Tasks.ReadWrite offline_access'
    }
    
    try:
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            # 如果返回了新的刷新令牌，输出提示
            new_refresh_token = result.get('refresh_token')
            if new_refresh_token and new_refresh_token != refresh_token:
                print("⚠️  注意: 获得了新的刷新令牌，请更新 MS_TODO_REFRESH_TOKEN")
                print(f"   新令牌: {new_refresh_token[:20]}...")
            
            return result.get('access_token')
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ 获取 MS 访问令牌失败: {e.code} - {error_body}")
        return None
    except Exception as e:
        print(f"❌ 获取 MS 访问令牌失败: {e}")
        return None


def get_client_credentials_token(tenant_id: str, client_id: str, client_secret: str) -> Optional[str]:
    """使用客户端凭证获取访问令牌（组织账户）"""
    url = f"{MS_LOGIN_BASE}/{tenant_id}/oauth2/v2.0/token"
    
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials',
        'scope': 'https://graph.microsoft.com/.default'
    }
    
    try:
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('access_token')
            
    except Exception as e:
        print(f"❌ 获取 MS 访问令牌失败: {e}")
        return None


def get_or_create_todo_list(access_token: str, list_name: str = "Lang-Monitor") -> Optional[str]:
    """获取或创建 To Do 列表，返回列表ID"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # 首先尝试获取现有列表
    try:
        req = urllib.request.Request(
            f"{MS_GRAPH_API_BASE}/me/todo/lists",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            for lst in result.get('value', []):
                if lst.get('displayName') == list_name:
                    return lst.get('id')
    except Exception as e:
        print(f"⚠️  获取 To Do 列表失败: {e}")
    
    # 如果列表不存在，创建新列表
    try:
        create_data = json.dumps({'displayName': list_name}).encode('utf-8')
        req = urllib.request.Request(
            f"{MS_GRAPH_API_BASE}/me/todo/lists",
            data=create_data,
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(f"✅ 已创建 To Do 列表: {list_name}")
            return result.get('id')
    except Exception as e:
        print(f"❌ 创建 To Do 列表失败: {e}")
        return None


def create_todo_task(access_token: str, list_id: str, update: dict) -> bool:
    """在 To Do 中创建任务"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # 构建任务标题和内容
    title = f"🔄 翻译更新: {update['name']} - {update['path'].split('/')[-1]}"
    
    # 构建任务描述（支持富文本）
    body_content = f"""<h3>📦 {update['name']}</h3>
<p><strong>仓库:</strong> {update['repo']}<br>
<strong>路径:</strong> {update['path']}<br>
<strong>分支:</strong> {update['branch']}<br>
<strong>作者:</strong> {update['commit_author']}<br>
<strong>时间:</strong> {update['commit_date']}</p>
<p><strong>提交信息:</strong> {update['commit_message']}</p>
<p>
<a href="{update['compare_url']}">📊 查看对比</a> | 
<a href="{update['commit_url']}">📝 查看提交</a> | 
<a href="{update['file_url']}">📄 查看文件</a>
</p>"""
    
    task_data = {
        'title': title,
        'body': {
            'content': body_content,
            'contentType': 'html'
        },
        'importance': 'normal',
        'linkedResources': [
            {
                'webUrl': update['file_url'],
                'applicationName': 'GitHub',
                'displayName': f"查看文件: {update['path']}"
            }
        ]
    }
    
    try:
        encoded_data = json.dumps(task_data).encode('utf-8')
        req = urllib.request.Request(
            f"{MS_GRAPH_API_BASE}/me/todo/lists/{list_id}/tasks",
            data=encoded_data,
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ 创建任务失败: {e.code} - {error_body}")
        return False
    except Exception as e:
        print(f"❌ 创建任务失败: {e}")
        return False


def create_todo_tasks(updates: List[dict], settings: dict) -> bool:
    """
    在 Microsoft To Do 中创建任务
    
    需要环境变量:
    - MS_TODO_CLIENT_ID: Azure AD 应用ID
    - MS_TODO_REFRESH_TOKEN: 刷新令牌
    
    或者:
    - MS_TODO_TENANT_ID: 租户ID（组织账户）
    - MS_TODO_CLIENT_ID: 应用ID
    - MS_TODO_CLIENT_SECRET: 客户端密码
    """
    # 检查是否配置了 Microsoft To Do
    if not os.environ.get('MS_TODO_CLIENT_ID'):
        print("⚠️  未配置 Microsoft To Do，跳过任务创建")
        return False
    
    print("\n📋 正在创建 Microsoft To Do 任务...")
    
    # 获取访问令牌
    access_token = get_ms_access_token()
    if not access_token:
        print("❌ 无法获取 Microsoft 访问令牌")
        return False
    
    # 获取或创建任务列表
    list_name = settings.get('todo_list_name', 'Lang-Monitor')
    list_id = get_or_create_todo_list(access_token, list_name)
    if not list_id:
        print("❌ 无法获取或创建 To Do 列表")
        return False
    
    # 创建任务
    success_count = 0
    for update in updates:
        if create_todo_task(access_token, list_id, update):
            success_count += 1
            print(f"   ✅ {update['name']}: {update['path']}")
        else:
            print(f"   ❌ {update['name']}: {update['path']}")
    
    print(f"\n✅ Microsoft To Do: 成功创建 {success_count}/{len(updates)} 个任务")
    return success_count > 0


# 需要导入 urllib.parse
import urllib.parse

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
        
        # 创建 Microsoft To Do 任务
        if os.environ.get('MS_TODO_CLIENT_ID'):
            create_todo_tasks(updates, settings)
        else:
            print("⚠️  未配置 Microsoft To Do，跳过任务创建")
            print("   设置 MS_TODO_* 环境变量以启用待办事项")
        
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
