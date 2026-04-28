from PIL import Image
import os

def convert_png_to_ico(png_path, ico_path):
    if not os.path.exists(png_path):
        print(f"Error: {png_path} not found.")
        return
    
    img = Image.open(png_path)
    # ICO通常包含多种尺寸以适应不同显示场景
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ico_path, sizes=icon_sizes)
    print(f"Successfully converted '{png_path}' to '{ico_path}'")

if __name__ == "__main__":
    # 默认转换 assets/icon.png
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(base_dir, 'assets', 'icon.png')
    dst = os.path.join(base_dir, 'assets', 'icon.ico')
    convert_png_to_ico(src, dst)