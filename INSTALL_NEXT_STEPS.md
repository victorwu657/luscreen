# 📦 生成安装包操作指南

## 当前状态
✅ 主程序已编译: `dist_nuitka/LuScreen.dist/LuScreen.exe`
✅ 安装脚本已创建: `installer.iss`
❌ 需要安装 Inno Setup

## 立即操作步骤

### 方法 1: 安装 Inno Setup 后构建 (推荐)

1. **下载 Inno Setup 6**
   ```
   https://jrsoftware.org/isdl.php
   下载 innosetup-6.x.x.exe
   ```

2. **安装到默认路径**
   ```
   C:\Program Files (x86)\Inno Setup 6\
   ```

3. **运行构建脚本**
   ```batch
   build_installer.bat
   ```

### 方法 2: 手动使用 Inno Setup (图形界面)

1. 安装 Inno Setup 后，打开程序
2. 点击 File > Open，选择 `installer.iss`
3. 点击 Build > Compile (或按 Ctrl+F9)
4. 等待编译完成
5. 安装包生成在 `dist_installer\` 目录

### 方法 3: 临时方案 - 手动打包

如果暂时不想安装 Inno Setup，可以手动创建便携版：

1. 复制整个 `dist_nuitka\LuScreen.dist\` 文件夹
2. 重命名为 `LuScreen-v0.046.9-Portable`
3. 压缩为 zip 文件
4. 用户解压后直接运行 `LuScreen.exe`

## 预期输出

安装包位置:
```
dist_installer\LuScreen-Setup-v0.046.9.exe
```

安装包大小: 约 100-300MB (不含模型)

## 下一步

安装包生成后需要：
1. 在干净的 Windows 系统测试安装
2. 测试字幕模型下载功能
3. 上传 `manifest.json` 到官网
4. 发布安装包
