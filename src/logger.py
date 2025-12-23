import logging
import sys
import os
import traceback
from datetime import datetime

def setup_global_logger():
    # 确定日志文件路径
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    log_dir = os.path.join(base_path, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    timestamp = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f'luscreen_{timestamp}.log')

    # 配置 logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout) # 同时输出到控制台
        ]
    )
    
    logger = logging.getLogger("Global")
    logger.info("Global logger initialized.")
    return logger

def handle_exception(exc_type, exc_value, exc_traceback):
    """
    全局异常捕获钩子
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger = logging.getLogger("Global")
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    # 将错误写入单独的 crash.log 以便快速查看
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    crash_file = os.path.join(base_path, 'crash.log')
    with open(crash_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*30}\n")
        f.write(f"Crash Time: {datetime.now()}\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)

# 安装钩子
sys.excepthook = handle_exception