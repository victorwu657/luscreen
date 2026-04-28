# LuScreen 安装包制作指南

## 前置要求

1. **安装 Inno Setup 6**
   - 下载地址: https://jrsoftware.org/isdl.php
   - 安装到默认路径: `C:\Program Files (x86)\Inno Setup 6\`

2. **编译主程序**
   - 运行 `build_nuitka.bat` 编译程序
   - 确保生成 `dist_nuitka\LuScreen.dist\LuScreen.exe`

## 构建步骤

### 方法 1: 使用自动化脚本 (推荐)

```batch
build_installer.bat
```

### 方法 2: 手动编译

1. 打开 Inno Setup Compiler
2. 打开 `installer.iss` 文件
3. 点击 Build > Compile
4. 等待编译完成

## 输出文件

编译完成后，安装包位于:
```
dist_installer\LuScreen-Setup-v0.046.9.exe
```

## 安装包功能

- ✅ 自动安装到 Program Files
- ✅ 创建桌面快捷方式
- ✅ 创建开始菜单项
- ✅ 可选开机自启动
- ✅ 完整的卸载程序
- ✅ 卸载时询问是否保留用户数据

## 模型下载配置

### 上传到官网

将以下文件上传到 `luscreen.com/downloads/models/`:

1. `manifest.json` - 模型配置文件
2. `whisperx-base.zip` - 基础模型压缩包
3. `whisperx-medium.zip` - 中等模型压缩包
4. `whisperx-large-v2.zip` - 大型模型压缩包

### 生成 MD5 校验值

```batch
certutil -hashfile whisperx-base.zip MD5
```

将生成的 MD5 值填入 `manifest.json` 对应位置。

## 测试清单

- [ ] 安装程序可以正常运行
- [ ] 桌面图标创建成功
- [ ] 程序可以正常启动
- [ ] 首次使用字幕功能时弹出下载提示
- [ ] 模型下载功能正常
- [ ] 卸载程序可以正常工作
- [ ] 卸载时正确询问是否保留数据

## 发布流程

1. 更新 `version.json` 版本号
2. 运行 `build_nuitka.bat` 编译程序
3. 运行 `build_installer.bat` 生成安装包
4. 测试安装包
5. 上传到官网
6. 更新下载链接
