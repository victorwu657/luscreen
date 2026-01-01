import time
import cv2
import numpy as np
import mss
from pynput.mouse import Controller, Button
from pynput import keyboard
from PySide6.QtCore import QObject, Signal, QThread
import os

class ScrollCaptureWorker(QThread):
    progress = Signal(int) # 发送已捕获的帧数
    finished = Signal(str) # 发送最终图片路径
    error = Signal(str)

    def __init__(self, region, output_path):
        super().__init__()
        self.region = region # 这里的 region 应该是逻辑坐标 (来自 Qt SelectionWidget)
        self.output_path = output_path
        self.mouse = Controller()
        self.is_running = True
        self.images = []
        self.listener = None

    def on_key_press(self, key):
        if key == keyboard.Key.esc:
            print("ESC pressed, stopping scroll capture...")
            self.stop()

    def stop(self):
        self.is_running = False

    def get_dpi_scale(self, sct):
        # 简单估算 DPI: 比较 mss 获取的屏幕宽度和 region 所在的逻辑屏幕宽度的关系
        # 但这里为了简单稳健，我们假设 region 已经是逻辑坐标，
        # 我们通过比较 monitor[width] / qt_primary_screen_width 来计算
        # 由于这里没有 QApplication 实例引用，我们采用另一种方法：
        # 直接使用 region，但在 capture_frame 时动态修正
        
        # 实际上，main.py 应该传入已经修正过 DPI 的物理坐标 region 更好，
        # 但为了兼容性，我们在这里做一次检测。
        # 如果 region 的宽度远小于 monitor 宽度，可能是逻辑坐标。
        
        # 最佳实践：假设传入的是 逻辑坐标，我们在这里乘以 scale。
        # 为了获取 scale，我们需要 Qt 的帮助，或者通过 ctypes。
        try:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            return screen.devicePixelRatio()
        except:
            return 1.0

    def run(self):
        try:
            self.listener = keyboard.Listener(on_press=self.on_key_press)
            self.listener.start()
            
            with mss.mss() as sct:
                # 计算 DPI
                scale = self.get_dpi_scale(sct)
                print(f"ScrollCapture: Detected DPI scale: {scale}")
                
                # 转换 region 为物理坐标
                phys_region = {
                    'top': int(self.region['top'] * scale),
                    'left': int(self.region['left'] * scale),
                    'width': int(self.region['width'] * scale),
                    'height': int(self.region['height'] * scale)
                }
                
                # 确保不超出屏幕
                monitor = sct.monitors[1]
                phys_region['left'] = max(monitor['left'], phys_region['left'])
                phys_region['top'] = max(monitor['top'], phys_region['top'])
                # 宽度限制暂且不加，相信 mss 会处理或报错
                
                print(f"ScrollCapture: Physical region: {phys_region}")

                # 1. 初始截图
                last_img = self.capture_frame(sct, phys_region)
                self.images.append(last_img)
                self.progress.emit(1)

                scroll_count = 0
                max_scrolls = 100 
                
                # 移动鼠标到中心
                center_x = self.region['left'] + self.region['width'] // 2
                center_y = self.region['top'] + self.region['height'] // 2
                self.mouse.position = (center_x, center_y)
                time.sleep(0.5)

                while self.is_running and scroll_count < max_scrolls:
                    # 模拟滚动 (Windows: -120 is one unit down, pynput uses units)
                    # 滚动幅度稍微大一点，减少拼接次数，但不能超过一屏
                    self.mouse.scroll(0, -4) 
                    time.sleep(0.8) # 等待滚动停止

                    if not self.is_running: break

                    curr_img = self.capture_frame(sct, phys_region)
                    
                    # 2. 实时去重检测 (判断到底)
                    if self.is_duplicate(last_img, curr_img):
                        print("Reached bottom (duplicate content)")
                        break
                        
                    self.images.append(curr_img)
                    last_img = curr_img
                    scroll_count += 1
                    self.progress.emit(len(self.images))
                    
                    # 可以在这里做实时拼接优化内存，但为了算法简单，先收集再拼接
            
            # 停止监听
            if self.listener:
                self.listener.stop()
            
            # 3. 拼接
            print(f"Stitching {len(self.images)} images...")
            if len(self.images) > 0:
                final_img = self.stitch_images_robust(self.images)
                
                if final_img is not None:
                    is_success, im_buf = cv2.imencode(".png", final_img)
                    if is_success:
                        im_buf.tofile(self.output_path)
                        self.finished.emit(self.output_path)
                    else:
                        self.error.emit("Failed to encode image")
                else:
                    self.error.emit("Stitching failed")
            else:
                 self.error.emit("No images captured")

        except Exception as e:
            if self.listener:
                self.listener.stop()
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

    def capture_frame(self, sct, region):
        img = sct.grab(region)
        frame = np.array(img)
        return frame[:,:,:3] # RGB only

    def is_duplicate(self, img1, img2):
        # 比较最后 100 行是否一致
        h, w, _ = img1.shape
        check_h = min(h, 100)
        roi1 = img1[h-check_h:h, :, :]
        roi2 = img2[h-check_h:h, :, :]
        
        diff = cv2.absdiff(roi1, roi2)
        mean_diff = np.mean(diff)
        return mean_diff < 2.0 # 允许微小差异

    def stitch_images_robust(self, images):
        if not images: return None
        if len(images) == 1: return images[0]

        # 使用 SIFT 算法 (Scale-Invariant Feature Transform)
        # SIFT 对文字细节特征提取非常优秀，配合强几何约束可以实现像素级拼接
        
        # SIFT 在 OpenCV 4.4+ 已免费可用
        try:
            detector = cv2.SIFT_create()
        except:
            print("SIFT not available, falling back to ORB")
            detector = cv2.ORB_create(nfeatures=5000)
            
        matcher = cv2.BFMatcher() # L2 norm for SIFT
        
        full_img = images[0]
        
        for i in range(1, len(images)):
            img_prev = images[i-1]
            img_curr = images[i]
            
            h_prev, w, _ = img_prev.shape
            h_curr, _, _ = img_curr.shape
            
            # 1. 定义感兴趣区域 (ROI) 加速匹配
            # 假设重叠区域在 prev 的底部 50% 和 curr 的顶部 50%
            roi_h_prev = int(h_prev * 0.6)
            roi_prev = img_prev[h_prev-roi_h_prev:h_prev, :, :]
            
            roi_h_curr = int(h_curr * 0.6)
            roi_curr = img_curr[0:roi_h_curr, :, :]
            
            # 转灰度
            gray_prev = cv2.cvtColor(roi_prev, cv2.COLOR_BGR2GRAY)
            gray_curr = cv2.cvtColor(roi_curr, cv2.COLOR_BGR2GRAY)
            
            # 2. 检测 SIFT 特征点
            kp1, des1 = detector.detectAndCompute(gray_prev, None)
            kp2, des2 = detector.detectAndCompute(gray_curr, None)
            
            if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
                print(f"Frame {i}: Not enough features. Appending.")
                full_img = np.vstack((full_img, img_curr))
                continue
                
            # 3. KNN 匹配
            matches = matcher.knnMatch(des1, des2, k=2)
            
            # 4. 筛选好点 (Lowe's ratio test) & 几何约束
            valid_dy = []
            
            for m, n in matches:
                if m.distance < 0.75 * n.distance:
                    # 获取坐标
                    pt1 = kp1[m.queryIdx].pt # (x, y) in roi_prev
                    pt2 = kp2[m.trainIdx].pt # (x, y) in roi_curr
                    
                    dx = pt1[0] - pt2[0]
                    dy = pt1[1] - pt2[1]
                    
                    # 几何约束 1: X 轴位移应该很小 (假设垂直滚动)
                    if abs(dx) > 5:
                        continue
                        
                    # 几何约束 2: Y 轴位移必须合理 (img_prev 在上，img_curr 在下)
                    # pt1.y 是在 prev 底部区域的坐标， pt2.y 是在 curr 顶部区域的坐标
                    # 真正的 y1_global = (h_prev - roi_h_prev) + pt1.y
                    # 真正的 y2_global = pt2.y (相对于 curr 起始点)
                    # 相对位移 shift = y1_global - y2_global
                    
                    global_y1 = (h_prev - roi_h_prev) + pt1[1]
                    shift_y = global_y1 - pt2[1]
                    
                    valid_dy.append(shift_y)
            
            if not valid_dy:
                print(f"Frame {i}: No valid geometric matches. Appending.")
                full_img = np.vstack((full_img, img_curr))
                continue
                
            # 5. 统计位移 (RANSAC 思想：找中位数)
            dy_array = np.array(valid_dy)
            median_dy = np.median(dy_array)
            
            # 过滤掉偏离中位数太远的点
            consistent_dy = dy_array[np.abs(dy_array - median_dy) < 3]
            
            if len(consistent_dy) == 0:
                final_shift = int(median_dy)
            else:
                final_shift = int(np.mean(consistent_dy))
            
            # 6. 拼接
            # final_shift 是 img_curr 相对于 img_prev 的起始位置
            # 即 overlap = h_prev - final_shift
            
            overlap_height = h_prev - final_shift
            
            print(f"Frame {i}: SIFT Shift={final_shift}, Overlap={overlap_height}, Matches={len(consistent_dy)}")
            
            if overlap_height > 0 and overlap_height < h_curr:
                # 裁剪 full_img
                # full_img 的末尾对应 img_prev
                # 我们要切掉 full_img 的最后 overlap_height
                
                cut_y = full_img.shape[0] - overlap_height
                
                if cut_y > 0:
                    img_top = full_img[0:cut_y, :, :]
                    full_img = np.vstack((img_top, img_curr))
                    continue
            
            print(f"  -> Invalid overlap. Appending.")
            full_img = np.vstack((full_img, img_curr))
            
        return full_img