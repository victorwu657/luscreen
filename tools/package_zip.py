import os
import sys
import zipfile
import shutil

# 添加项目根目录到路径以便导入 src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.version import APP_VERSION

def zip_folder(folder_path, output_path):
    print(f"Compressing {folder_path} to {output_path}...")
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                # 计算相对路径，保持ZIP内结构整洁
                arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                zipf.write(file_path, arcname)
    print("Compression complete!")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(base_dir, 'dist_nuitka', 'LuScreen.dist')
    
    if not os.path.exists(dist_dir):
        print(f"Error: Build directory not found: {dist_dir}")
        print("Please run build_nuitka.bat first.")
        sys.exit(1)
        
    output_zip = os.path.join(base_dir, 'dist_nuitka', 'LuScreen.zip')
    
    zip_folder(dist_dir, output_zip)