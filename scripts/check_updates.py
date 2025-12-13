#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lang-Monitor: 语言文件更新监控器
监控指定GitHub仓库中的文件变更，并发送邮件通知
"""

import json
import os
import sys
import re
import fnmatch
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
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


def github_api_request(endpoint: str, token: Optional[str] = None) -> Tuple[Optional[Any], Optional[str]]:
    """发送GitHub API请求"""
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
            return json.loads(response.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        errors = {404: "仓库或路径不存在", 403: "API请求限制或权限不足"}
        return None, errors.get(e.code, f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        return None, f"网络错误: {e.reason}"
    except Exception as e:
        return None, f"未知错误: {str(e)}"


def get_path_commits(repo: str, branch: str, path: str, token: Optional[str] = None):
    """获取指定路径的最新提交"""
    endpoint = f"/repos/{repo}/commits?sha={branch}&path={path}&per_page=1"
    return github_api_request(endpoint, token)


def get_repo_tree(repo: str, branch: str, token: Optional[str] = None) -> Tuple[Optional[List[str]], Optional[str]]:
    """获取仓库的完整文件树"""
    endpoint = f"/repos/{repo}/git/trees/{branch}?recursive=1"
    data, error = github_api_request(endpoint, token)
    if error:
        return None, error
    if data and 'tree' in data:
        return [item['path'] for item in data['tree'] if item['type'] == 'blob'], None
    return [], None


def expand_glob_pattern(repo: str, branch: str, pattern: str, token: Optional[str] = None) -> List[str]:
    """展开通配符模式，返回匹配的文件路径列表"""
    # 获取仓库文件树
    files, error = get_repo_tree(repo, branch, token)
    if error or not files:
        print(f"      ⚠️ 无法获取文件树: {error}")
        return []
    
    # 使用 fnmatch 进行通配符匹配
    matched = []
    for file_path in files:
        if fnmatch.fnmatch(file_path, pattern):
            matched.append(file_path)
    
    return matched


def expand_regex_pattern(repo: str, branch: str, pattern: str, token: Optional[str] = None) -> List[str]:
    """展开正则表达式模式，返回匹配的文件路径列表"""
    # 获取仓库文件树
    files, error = get_repo_tree(repo, branch, token)
    if error or not files:
        print(f"      ⚠️ 无法获取文件树: {error}")
        return []
    
    # 使用正则表达式匹配
    try:
        regex = re.compile(pattern)
        matched = [f for f in files if regex.search(f)]
        return matched
    except re.error as e:
        print(f"      ❌ 正则表达式错误: {e}")
        return []


def process_path_template(template: str, variables: Dict[str, str]) -> str:
    """处理路径模板，替换变量"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def expand_monitors(config: dict) -> List[dict]:
    """
    展开配置，处理各种便捷语法：
    - templates: 模板定义
    - defaults: 默认值
    - batch: 批量配置
    - 普通 monitors
    """
    expanded = []
    
    # 获取模板定义
    templates = config.get('templates', {})
    
    # 获取默认值
    defaults = config.get('defaults', {})
    
    # 处理批量配置
    for batch in config.get('batch', []):
        repos = batch.get('repos', [])
        base_config = {k: v for k, v in batch.items() if k != 'repos'}
        
        for repo in repos:
            monitor = {**defaults, **base_config, 'repo': repo}
            
            # 如果没有 name，自动生成
            if 'name' not in monitor:
                monitor['name'] = repo.split('/')[-1]
            
            expanded.append(monitor)
    
    # 处理普通监控项
    for monitor in config.get('monitors', []):
        # 应用默认值
        final_monitor = {**defaults, **monitor}
        
        # 处理模板引用
        if 'template' in final_monitor:
            template_name = final_monitor.pop('template')
            if template_name in templates:
                template_config = templates[template_name]
                # 模板配置优先级低于直接配置
                for key, value in template_config.items():
                    if key not in final_monitor:
                        final_monitor[key] = value
        
        # 处理路径模板变量
        if 'vars' in final_monitor and 'paths' in final_monitor:
            variables = final_monitor.get('vars', {})
            final_monitor['paths'] = [
                process_path_template(p, variables) for p in final_monitor['paths']
            ]
        
        expanded.append(final_monitor)
    
    return expanded


def check_for_updates(config: dict, state: dict, token: Optional[str] = None) -> List[dict]:
    """检查所有监控项的更新"""
    updates = []
    monitors_state = state.get('monitors', {})
    
    # 展开配置
    monitors = expand_monitors(config)
    
    # 用于去重（相同 repo:branch:path 只检查一次）
    checked_keys = set()
    
    for monitor in monitors:
        if not monitor.get('enabled', True):
            print(f"⏭️  跳过已禁用: {monitor.get('name', monitor.get('repo', 'unknown'))}")
            continue
        
        repo = monitor.get('repo')
        if not repo:
            print(f"⚠️  跳过无效配置（缺少 repo）")
            continue
            
        branch = monitor.get('branch', 'main')
        name = monitor.get('name', repo.split('/')[-1])
        
        print(f"\n🔍 检查: {name} ({repo})")
        
        # 收集所有需要检查的路径
        paths_to_check = []
        
        # 1. 普通路径
        paths_to_check.extend(monitor.get('paths', []))
        
        # 2. 通配符路径 (glob)
        for pattern in monitor.get('paths_glob', []):
            print(f"   🔎 展开通配符: {pattern}")
            matched = expand_glob_pattern(repo, branch, pattern, token)
            if matched:
                print(f"      ✅ 匹配到 {len(matched)} 个文件")
                paths_to_check.extend(matched)
            else:
                print(f"      ⚠️ 无匹配文件")
        
        # 3. 正则表达式路径
        for pattern in monitor.get('paths_regex', []):
            print(f"   🔎 展开正则: {pattern}")
            matched = expand_regex_pattern(repo, branch, pattern, token)
            if matched:
                print(f"      ✅ 匹配到 {len(matched)} 个文件")
                paths_to_check.extend(matched)
            else:
                print(f"      ⚠️ 无匹配文件")
        
        # 检查每个路径
        for path in paths_to_check:
            key = f"{repo}:{branch}:{path}"
            
            # 去重检查
            if key in checked_keys:
                continue
            checked_keys.add(key)
            
            print(f"   📁 {path}", end=" ")
            
            commits, error = get_path_commits(repo, branch, path, token)
            
            if error:
                print(f"❌ {error}")
                continue
            
            if not commits:
                print("⚠️ 无提交记录")
                continue
            
            latest = commits[0]
            latest_sha = latest['sha']
            previous_sha = monitors_state.get(key, {}).get('last_sha')
            
            if previous_sha is None:
                print(f"📝 首次记录")
                monitors_state[key] = {'last_sha': latest_sha, 'last_check': datetime.now(timezone.utc).isoformat()}
            elif previous_sha != latest_sha:
                print(f"🆕 有更新!")
                updates.append({
                    'name': name,
                    'repo': repo,
                    'branch': branch,
                    'path': path,
                    'old_sha': previous_sha,
                    'new_sha': latest_sha,
                    'commit_message': latest['commit']['message'].split('\n')[0],
                    'commit_date': latest['commit']['committer']['date'],
                    'commit_author': latest['commit']['author']['name'],
                    'compare_url': f"https://github.com/{repo}/compare/{previous_sha[:7]}...{latest_sha[:7]}",
                    'commit_url': f"https://github.com/{repo}/commit/{latest_sha}",
                    'file_url': f"https://github.com/{repo}/blob/{branch}/{path}"
                })
                monitors_state[key] = {'last_sha': latest_sha, 'last_check': datetime.now(timezone.utc).isoformat()}
            else:
                print(f"✅ 无变化")
    
    state['monitors'] = monitors_state
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    return updates


def format_email_content(updates: List[dict], settings: dict) -> Tuple[str, str]:
    """格式化邮件内容"""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # 按仓库分组
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
        f"⏰ 检查时间: {now}",
        f"📊 更新: {repo_count} 个仓库 / {file_count} 个文件",
        "━" * 50, ""
    ]
    
    for repo, repo_updates in updates_by_repo.items():
        text_lines.append(f"📦 {repo}")
        text_lines.append("-" * 40)
        for u in repo_updates:
            text_lines.extend([
                f"  📄 {u['path']}",
                f"     作者: {u['commit_author']} | 时间: {u['commit_date']}",
                f"     提交: {u['commit_message']}",
                f"     🔗 {u['compare_url']}",
                ""
            ])
    
    # HTML版本
    primary_color = "#0969da"
    bg_color = "#f6f8fa"
    border_color = "#d0d7de"
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lang-Monitor Updates</title>
</head>
<body style="margin:0;padding:0;background-color:{bg_color};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif,'Apple Color Emoji','Segoe UI Emoji';color:#24292f;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{bg_color};width:100%;">
        <tr>
            <td align="center" style="padding:20px;">
                <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:6px;border:1px solid {border_color};overflow:hidden;box-shadow: 0 3px 6px rgba(140,149,159,0.15);">
                    <!-- Header -->
                    <tr>
                        <td style="padding:24px;background-color:#ffffff;border-bottom:1px solid {border_color};text-align:center;">
                            <h1 style="margin:0;font-size:20px;font-weight:600;color:#24292f;">📢 翻译文件更新通知</h1>
                            <p style="margin:8px 0 0;font-size:14px;color:#57606a;">Lang-Monitor 自动检测</p>
                        </td>
                    </tr>
                    
                    <!-- Stats -->
                    <tr>
                        <td style="padding:16px 24px;background-color:#ffffff;border-bottom:1px solid {border_color};">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td align="center" width="33%" style="border-right:1px solid {border_color};">
                                        <div style="font-size:24px;font-weight:600;color:{primary_color};">{repo_count}</div>
                                        <div style="font-size:12px;color:#57606a;">仓库</div>
                                    </td>
                                    <td align="center" width="33%" style="border-right:1px solid {border_color};">
                                        <div style="font-size:24px;font-weight:600;color:{primary_color};">{file_count}</div>
                                        <div style="font-size:12px;color:#57606a;">文件</div>
                                    </td>
                                    <td align="center" width="33%">
                                        <div style="font-size:14px;font-weight:600;color:#24292f;">{now.split(' ')[0]}</div>
                                        <div style="font-size:12px;color:#57606a;">{now.split(' ')[1]} UTC</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding:24px;">"""
    
    for repo, repo_updates in updates_by_repo.items():
        html += f"""
                            <div style="margin-bottom:24px;">
                                <div style="display:flex;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid {border_color};">
                                    <span style="font-size:16px;font-weight:600;color:#24292f;">📦 {repo}</span>
                                </div>"""
        
        for u in repo_updates:
            html += f"""
                                <div style="margin-bottom:16px;border:1px solid {border_color};border-radius:6px;overflow:hidden;">
                                    <div style="background-color:{bg_color};padding:8px 12px;border-bottom:1px solid {border_color};font-size:12px;color:#57606a;font-family:ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace;word-break:break-all;">
                                        {u['path']}
                                    </div>
                                    <div style="padding:12px;">
                                        <div style="margin-bottom:8px;">
                                            <span style="display:inline-block;padding:2px 6px;background-color:#ddf4ff;color:{primary_color};border-radius:10px;font-size:12px;font-weight:500;border:1px solid rgba(9,105,218,0.2);margin-right:6px;">{u['name']}</span>
                                            <span style="font-size:14px;font-weight:600;color:#24292f;">{u['commit_message']}</span>
                                        </div>
                                        
                                        <div style="font-size:12px;color:#57606a;margin-bottom:12px;">
                                            👤 {u['commit_author']} &nbsp;•&nbsp; 🕒 {u['commit_date']}
                                        </div>
                                        
                                        <div>
                                            <a href="{u['compare_url']}" style="text-decoration:none;display:inline-block;padding:5px 12px;background-color:{bg_color};color:#24292f;border:1px solid {border_color};border-radius:6px;font-size:12px;font-weight:500;margin-right:4px;">📊 对比</a>
                                            <a href="{u['commit_url']}" style="text-decoration:none;display:inline-block;padding:5px 12px;background-color:{bg_color};color:#24292f;border:1px solid {border_color};border-radius:6px;font-size:12px;font-weight:500;margin-right:4px;">📝 提交</a>
                                            <a href="{u['file_url']}" style="text-decoration:none;display:inline-block;padding:5px 12px;background-color:{bg_color};color:#24292f;border:1px solid {border_color};border-radius:6px;font-size:12px;font-weight:500;">📄 文件</a>
                                        </div>
                                    </div>
                                </div>"""
        html += "</div>"
    
    html += f"""</td></tr>
    <!-- Footer -->
    <tr><td style="background-color:{bg_color};padding:20px;border-top:1px solid {border_color};text-align:center;">
        <p style="margin:0;color:#57606a;font-size:12px;">
            Generated by <a href="https://github.com/nageih/Lang-Monitor" style="color:{primary_color};text-decoration:none;">Lang-Monitor</a>
        </p>
    </td></tr>
</table>
</td></tr></table>
</body></html>"""
    
    return '\n'.join(text_lines), html


def send_email(updates: List[dict], settings: dict) -> bool:
    """发送邮件通知"""
    smtp_server = os.environ.get('EMAIL_SMTP_SERVER')
    smtp_port = int(os.environ.get('EMAIL_SMTP_PORT', '587'))
    username = os.environ.get('EMAIL_USERNAME')
    password = os.environ.get('EMAIL_PASSWORD')
    to_email = os.environ.get('EMAIL_TO')
    
    if not all([smtp_server, username, password, to_email]):
        print("❌ 邮件配置不完整")
        return False
    
    # 生成标题
    prefix = settings.get('email_subject_prefix', '[Lang-Monitor]')
    repo_count = len(set(u['repo'] for u in updates))
    if repo_count == 1:
        subject = f"{prefix} 📢 {updates[0]['repo'].split('/')[-1]} 有 {len(updates)} 个文件更新"
    else:
        subject = f"{prefix} 📢 {repo_count} 个仓库共 {len(updates)} 个文件更新"
    
    text_content, html_content = format_email_content(updates, settings)
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = formataddr((settings.get('email_sender_name', 'Lang-Monitor'), username))
    msg['To'] = to_email
    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    try:
        print(f"\n📧 发送邮件到: {to_email}")
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
        else:
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
    
    # 路径设置
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    config_path = os.path.join(root_dir, 'config', 'monitors.json')
    state_path = os.path.join(root_dir, 'data', 'state.json')
    
    # 加载配置和状态
    config = load_json_file(config_path)
    state = load_json_file(state_path)
    
    if not config.get('monitors') and not config.get('batch'):
        print("❌ 未找到监控配置，请编辑 config/monitors.json")
        sys.exit(1)
    
    settings = config.get('settings', {})
    
    # GitHub Token
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        print("⚠️  未设置 GITHUB_TOKEN，API请求可能受限")
    
    # 检查更新
    updates = check_for_updates(config, state, github_token)
    
    # 保存状态
    save_json_file(state_path, state)
    print(f"\n💾 状态已保存")
    
    # 处理结果
    print("\n" + "=" * 50)
    if updates:
        print(f"📢 发现 {len(updates)} 个更新!")
        
        # 发送邮件
        if os.environ.get('EMAIL_SMTP_SERVER'):
            send_email(updates, settings)
        else:
            print("⚠️  未配置邮件，跳过发送")
        
        # GitHub Actions 输出
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"has_updates=true\nupdate_count={len(updates)}\n")
        
        print("\n📋 更新详情:")
        for u in updates:
            print(f"  • {u['name']}: {u['path']}")
    else:
        print("✅ 所有监控项均无更新")
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write("has_updates=false\nupdate_count=0\n")
    
    print("=" * 50)
    return 0


if __name__ == '__main__':
    sys.exit(main())
