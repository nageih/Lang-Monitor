#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Microsoft To Do 授权助手
用于获取 Microsoft Graph API 的刷新令牌

使用方法:
1. 在 Azure Portal 创建应用注册
2. 运行此脚本，按照提示操作
3. 将获取的 refresh_token 保存到 GitHub Secrets
"""

import http.server
import urllib.parse
import urllib.request
import json
import webbrowser
import threading
import sys

# 默认配置（个人微软账户）
DEFAULT_CLIENT_ID = ""  # 需要用户填入

# 授权端点
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
REDIRECT_URI = "http://localhost:8400/callback"
SCOPES = "Tasks.ReadWrite offline_access"

# 存储授权码
auth_code = None
server_ready = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """处理 OAuth 回调"""
    
    def do_GET(self):
        global auth_code
        
        # 解析回调参数
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>授权成功</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                           display: flex; justify-content: center; align-items: center; 
                           height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
                    .card { background: white; padding: 40px; border-radius: 16px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
                    h1 { color: #28a745; margin: 0 0 16px 0; }
                    p { color: #666; margin: 0; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>✅ 授权成功!</h1>
                    <p>请返回终端查看刷新令牌</p>
                    <p style="margin-top: 16px; color: #999;">可以关闭此页面</p>
                </div>
            </body>
            </html>
            """.encode('utf-8'))
        else:
            error = params.get('error', ['Unknown error'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"><title>授权失败</title></head>
            <body>
                <h1>❌ 授权失败</h1>
                <p>错误: {error}</p>
            </body>
            </html>
            """.encode())
    
    def log_message(self, format, *args):
        pass  # 禁用日志输出


def start_callback_server():
    """启动回调服务器"""
    server = http.server.HTTPServer(('localhost', 8400), CallbackHandler)
    server_ready.set()
    server.handle_request()  # 只处理一个请求


def get_tokens(client_id: str, auth_code: str) -> dict:
    """使用授权码换取令牌"""
    data = {
        'client_id': client_id,
        'code': auth_code,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
        'scope': SCOPES
    }
    
    encoded_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(TOKEN_URL, data=encoded_data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def main():
    print("=" * 60)
    print("🔑 Microsoft To Do 授权助手")
    print("=" * 60)
    print()
    print("此脚本将帮助你获取 Microsoft Graph API 的刷新令牌")
    print("用于在 GitHub Actions 中访问你的 Microsoft To Do")
    print()
    print("-" * 60)
    print("📋 准备工作 (如果还没有创建 Azure AD 应用):")
    print("-" * 60)
    print()
    print("1. 访问 https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade")
    print("2. 点击 '新注册'")
    print("3. 名称填写: Lang-Monitor")
    print("4. 账户类型选择: '任何组织目录中的账户和个人 Microsoft 账户'")
    print("5. 重定向 URI 选择 'Web'，填写: http://localhost:8400/callback")
    print("6. 点击 '注册'")
    print("7. 复制 '应用程序(客户端) ID'")
    print()
    print("8. 在左侧菜单中点击 'API 权限'")
    print("9. 点击 '添加权限' -> 'Microsoft Graph' -> '委托的权限'")
    print("10. 搜索并勾选: Tasks.ReadWrite, offline_access")
    print("11. 点击 '添加权限'")
    print()
    print("-" * 60)
    
    # 获取 Client ID
    client_id = input("\n请输入你的 Client ID (应用程序ID): ").strip()
    
    if not client_id:
        print("❌ Client ID 不能为空")
        sys.exit(1)
    
    # 启动回调服务器
    server_thread = threading.Thread(target=start_callback_server, daemon=True)
    server_thread.start()
    server_ready.wait()
    
    # 构建授权 URL
    auth_params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'response_mode': 'query'
    }
    
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    
    print()
    print("🌐 正在打开浏览器进行授权...")
    print("   如果浏览器没有自动打开，请手动访问以下链接:")
    print()
    print(f"   {auth_url}")
    print()
    
    webbrowser.open(auth_url)
    
    # 等待回调
    print("⏳ 等待授权完成...")
    server_thread.join(timeout=300)  # 5分钟超时
    
    if not auth_code:
        print("❌ 授权超时或失败")
        sys.exit(1)
    
    print("✅ 收到授权码，正在获取令牌...")
    
    try:
        tokens = get_tokens(client_id, auth_code)
        
        print()
        print("=" * 60)
        print("🎉 授权成功!")
        print("=" * 60)
        print()
        print("请将以下信息添加到 GitHub 仓库的 Secrets 中:")
        print("(Settings -> Secrets and variables -> Actions -> New repository secret)")
        print()
        print("-" * 60)
        print("Secret 名称: MS_TODO_CLIENT_ID")
        print(f"Secret 值: {client_id}")
        print("-" * 60)
        print("Secret 名称: MS_TODO_REFRESH_TOKEN")
        print(f"Secret 值: {tokens['refresh_token']}")
        print("-" * 60)
        print()
        print("⚠️  重要提示:")
        print("   - 刷新令牌非常敏感，请妥善保管")
        print("   - 不要将令牌提交到代码仓库")
        print("   - 令牌可能会过期，届时需要重新运行此脚本")
        print()
        
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ 获取令牌失败: {e.code}")
        print(f"   {error_body}")
        sys.exit(1)


if __name__ == '__main__':
    main()
