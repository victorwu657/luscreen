# 📥 Inno Setup 安装说明

## 下载失败原因
网络连接被重置，无法自动下载。

## 手动安装步骤

### 方法 1: 官方网站下载
1. 访问: https://jrsoftware.org/isdl.php
2. 下载 **Inno Setup 6.3.3** (约 2MB)
3. 双击运行安装程序
4. 使用默认设置安装到: `C:\Program Files (x86)\Inno Setup 6\`
5. 安装完成后运行: `build_installer.bat`

### 方法 2: 国内镜像下载
1. 访问清华镜像: https://mirrors.tuna.tsinghua.edu.cn/github-release/jrsoftware/issrc/
2. 下载最新版本
3. 按上述步骤安装

### 方法 3: 使用便携版 (无需安装)
1. 下载 Inno Setup Portable
2. 解压到任意目录
3. 修改 `build_installer.bat` 中的路径指向便携版

## 安装完成后

运行构建脚本:
```batch
build_installer.bat
```

或手动编译:
1. 打开 Inno Setup Compiler
2. 打开 `installer.iss`
3. 点击 Build > Compile

## 验证安装

检查路径是否存在:
```
C:\Program Files (x86)\Inno Setup 6\ISCC.exe
```

---

**提示**: 如果你已经有 Inno Setup 安装在其他位置，请修改 `build_installer.bat` 中的 ISCC 路径。
