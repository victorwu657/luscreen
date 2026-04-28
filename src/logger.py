import logging
import sys
import os
import traceback
from datetime import datetime
from src.version import APP_VERSION

class StreamToLogger:
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        pass

def setup_global_logger(redirect_stdout=True):
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
    # 移除 StreamHandler 以避免重定向 stdout 时的无限递归
    handlers = [
        logging.FileHandler(log_file, encoding='utf-8'),
    ]
    
    # 如果不重定向 stdout，则保留控制台输出
    if not redirect_stdout:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
        force=True # 强制重新配置
    )
    
    # 打印分隔符，区分每次运行
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'-'*80}\n")
        f.write(f"Session Started: {datetime.now()} | Version: {APP_VERSION}\n")
        f.write(f"{'-'*80}\n")
    
    logger = logging.getLogger("Global")
    logger.info(f"Global logger initialized. Version: {APP_VERSION}")
    logger.info(f"Log file: {log_file}")
    
    if redirect_stdout:
        sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO)
        sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR)
        logger.info("Stdout/Stderr redirected to log file.")
        
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
        
    log_dir = os.path.join(base_path, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    crash_file = os.path.join(log_dir, 'crash.log')
    with open(crash_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*30}\n")
        f.write(f"Crash Time: {datetime.now()}\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)

# 安装钩子
sys.excepthook = handle_exception