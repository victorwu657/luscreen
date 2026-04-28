import argparse
import os
import sys


def _emit_progress(value: int, message: str):
    value = max(0, min(100, int(value)))
    sys.stdout.write(f"PROGRESS\t{value}\t{message}\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=["openai"])
    parser.add_argument("--audio", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--api_key")
    parser.add_argument("--base_url")
    args = parser.parse_args()

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("LUSCREEN_ASR_DEVICE", "cpu")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    _emit_progress(40, "正在加载模型...")
    from src.subtitle_system.engines.openai_engine import OpenAIEngine

    engine = OpenAIEngine(api_key=args.api_key or "", base_url=args.base_url)

    _emit_progress(60, "正在识别语音...")
    segments = engine.transcribe(args.audio)

    _emit_progress(90, "正在生成字幕文件...")
    from src.subtitle_system.formatter import SubtitleFormatter

    srt_content = SubtitleFormatter.to_srt(segments)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(srt_content)

    _emit_progress(100, "完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
