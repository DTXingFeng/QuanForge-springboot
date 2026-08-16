# 部署到树莓派（或任意 Linux/ARM64 机器）

单 jar 部署：前端静态资源打进 Spring Boot fat jar，目标机只需要 JRE 21，无需 Node/Maven。

## 一、在开发机（Windows）上打包

```powershell
.\package.ps1
# 产物: target/QuanForge-springboot-0.0.1-SNAPSHOT.jar
```

> ⚠️ 在配置了 `application-local.yaml`（真实加密密钥）的机器上打包时，密钥会进入 jar。
> jar 与数据库配套，**不要把 jar 分发给他人**。

## 二、树莓派准备

### 1. Java 21

```bash
# Raspberry Pi OS Trixie / Ubuntu 24.04+（仓库自带 21）
sudo apt update && sudo apt install -y openjdk-21-jre-headless

# 若发行版仓库只有 17（如 Bookworm），用 Temurin：
# https://adoptium.net/temurin/releases/?version=21 （Linux aarch64 tarball）
```

验证：`java -version` 显示 21.x。

### 2. 目录与文件

开发机上传（jar、加密密钥、现有数据库——三者配套迁移后凭证/AI配置/代理设置全部保留）：

```powershell
# 开发机上执行（先停掉本地后端，避免数据库写中途拷贝）
scp target/QuanForge-springboot-0.0.1-SNAPSHOT.jar pi@<PI_IP>:/tmp/quanforge.jar
scp src/main/resources/application-local.yaml pi@<PI_IP>:/tmp/
scp data/quanforge.db pi@<PI_IP>:/tmp/          # 想全新开始可跳过此条
```

树莓派上就位：

```bash
sudo mkdir -p /opt/quanforge
sudo mv /tmp/quanforge.jar /opt/quanforge/
sudo mv /tmp/application-local.yaml /opt/quanforge/   # 与 jar 同目录，Spring 自动读取
sudo mv /tmp/quanforge.db /opt/quanforge/data-quanforge.db 2>/dev/null || true
# 数据库默认落在工作目录 data/ 下：
mkdir -p /opt/quanforge/data
sudo mv /tmp/quanforge.db /opt/quanforge/data/ 2>/dev/null || true
sudo chown -R pi:pi /opt/quanforge
```

> 代理：应用内代理配置指向 127.0.0.1:7890，与树莓派上的 Clash 端口一致，无需改动。
> 若全新数据库：首次打开页面后在「设置」页录入 Bybit 凭证、AI Key、代理。

### 3. systemd 常驻

```bash
sudo cp /opt/quanforge/quanforge.service /etc/systemd/system/ 2>/dev/null || \
  sudo wget -O /etc/systemd/system/quanforge.service <从仓库 deploy/ 目录拷贝>
# （仓库内 deploy/quanforge.service 已随代码提供，scp 上来即可）
sudo systemctl daemon-reload
sudo systemctl enable --now quanforge
```

验证：`curl http://127.0.0.1:8080/api/ai/config`，然后浏览器访问 `http://<PI_IP>:8080`。

## 三、日常运维

```bash
systemctl status quanforge        # 状态
journalctl -u quanforge -f        # 或 tail -f /var/log/quanforge.log
sudo systemctl restart quanforge  # 重启（更新 jar 后）
```

更新版本：开发机重新 `.\package.ps1` → scp 覆盖 `/opt/quanforge/quanforge.jar` → restart。

## 安全提醒

- 本服务**无鉴权**，仅限家庭内网使用；路由器上不要做端口转发。
- 树莓派 SD 卡寿命有限，SQLite 写入量小（分钟级），一般无碍；在意的话把 `/opt/quanforge/data`
  挪到外接 SSD 并软链回来。

## 内存参考

| Pi 型号 | 建议 -Xmx |
|---------|-----------|
| 2GB（Pi 4/Zero 2） | 512m（默认配置即可） |
| 4GB+（Pi 4/5） | 1g |

空载实测约 300MB；AI 研判峰值约 +150MB。
