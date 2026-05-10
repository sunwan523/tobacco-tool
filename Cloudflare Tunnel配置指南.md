# 🌐 Cloudflare Tunnel 配置指南

## ⚠️ 重要提示

**不会修改您的现有 Cloudflare Tunnel 配置！**

本指南仅提供配置说明，您可以手动在 Cloudflare 控制面板中完成配置，不会影响已有的其他项目配置。

---

## 📋 前提条件

1. ✅ 已在 Cloudflare 控制面板中添加了路由（您提到已完成）
2. ✅ 价格查询应用正在运行（端口：8502）
3. ✅ Cloudflare Tunnel 已安装并正常运行

---

## 🎯 配置步骤

### 方式一：通过 Cloudflare 控制面板（推荐）

#### 1. 确认应用正在运行
```powershell
# 检查应用状态
.\manage_price_query.ps1 status
```

#### 2. 访问 Cloudflare Zero Trust 面板
- 登录 https://one.dash.cloudflare.com
- 进入 **Networks** → **Tunnels**

#### 3. 选择您的 Tunnel
- 点击您正在使用的 Tunnel
- 进入 **Public Hostname** 标签

#### 4. 添加或确认路由配置
添加以下配置（如果还没有的话）：

| 配置项 | 值 |
|--------|-----|
| **Subdomain** | 您想使用的子域名（例如：price） |
| **Domain** | 您的域名（例如：yourdomain.com） |
| **Service Type** | HTTP |
| **URL** | localhost:8502 |

**最终效果**：访问 `https://price.yourdomain.com` 会转发到本地 `http://localhost:8502`

---

### 方式二：通过命令行配置

如果您想通过命令行操作，使用以下命令（仅作为参考）：

```powershell
# 查看现有 Tunnel
cloudflared tunnel list

# 查看现有配置（不会修改任何内容）
cloudflared tunnel info <您的Tunnel名称>
```

---

## ✅ 验证配置

### 1. 检查本地应用
```powershell
# 查看状态
.\manage_price_query.ps1 status

# 如果没运行，启动它
.\manage_price_query.ps1 start
```

### 2. 本地测试访问
打开浏览器访问：http://localhost:8502

### 3. 外网测试访问
通过您配置的 Cloudflare 域名访问（例如：https://price.yourdomain.com）

---

## 🔧 管理脚本使用

### 启动应用
```powershell
.\manage_price_query.ps1 start
```

### 停止应用
```powershell
.\manage_price_query.ps1 stop
```

### 查看状态
```powershell
.\manage_price_query.ps1 status
```

### 安装开机自启动
```powershell
# 右键使用"以管理员身份运行"
.\install_price_query_autostart.ps1
```

### 卸载开机自启动
```powershell
.\install_price_query_autostart.ps1 -Uninstall
```

---

## 📊 端口分配参考

从您的截图看，现有配置：

| 服务 | 端口 |
|------|------|
| nc.pn... | 8080 |
| yc.pn... | 8081 |
| qt.pn... | 8080 |
| zt.pn... | 8080 |

**新增**：
- 价格查询应用：8502

---

## 🛟 故障排查

### 问题1：外网无法访问
**检查清单**：
- ✅ 本地 http://localhost:8502 是否能正常打开
- ✅ Cloudflare Tunnel 是否在运行
- ✅ Public Hostname 配置是否正确指向 8502 端口
- ✅ 是否有防火墙阻止

### 问题2：应用无法启动
```powershell
# 查看端口是否被占用
netstat -ano | findstr ":8502"

# 查看详细状态
.\manage_price_query.ps1 status
```

### 问题3：查看日志
日志文件位置：`logs\price_query_app.log`

---

## 📝 完整配置示例（仅供参考）

如果您需要完整配置参考（不影响现有配置）：

**价格查询应用配置**：
```
Subdomain: price
Domain: yourdomain.com
Service: HTTP
URL: localhost:8502
```

---

## 🔒 安全提示

1. 保持 Cloudflare Tunnel 更新
2. 定期检查访问日志
3. 不要将管理接口暴露到外网
4. 管理员功能需要密码保护（523626）

---

## 💡 提示

- 您的 Cloudflare Tunnel 配置完全独立管理
- 本项目仅提供本地服务，不修改任何 Tunnel 配置
- 所有现有项目的配置都不会被影响
