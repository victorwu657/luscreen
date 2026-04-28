# 🚀 打包完整版指南

## 快速开始

运行此脚本即可：

```batch
build_full_version.bat
```

## 工作原理

1. 临时修改 `build_nuitka.bat`，移除 torch/whisperx 排除
2. 运行 Nuitka 编译（包含所有依赖）
3. 生成完整版安装包
4. 自动恢复原配置

## 预计时间

- 编译: 30-60 分钟
- 打包: 2-5 分钟
- 总计: 约 1 小时

## 输出文件

- `dist_installer\LuScreen-Full-Setup-v0.046.9.exe` (约 2-3GB)

## 注意事项

- 确保有足够磁盘空间（至少 10GB）
- 编译期间 CPU 占用较高
- 不要中断编译过程

运行完成后即可上传到官网！
