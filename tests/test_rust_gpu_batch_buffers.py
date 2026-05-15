import os
import sys
import unittest

import numpy as np


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


PROJECT_ROOT = _project_root()
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.video_processor import VideoProcessor


class TestRustGpuBatchBuffers(unittest.TestCase):
    def _load_gpu_processor(self):
        try:
            rust_core = VideoProcessor._load_rust_core(
                required_attrs=("GpuProcessor",),
                context="test_rust_gpu_batch_buffers",
            )
        except ImportError as exc:
            raise unittest.SkipTest(f"rust_core 不可用: {exc}")

        processor_cls = getattr(rust_core, "GpuProcessor", None)
        if processor_cls is None:
            raise unittest.SkipTest("rust_core 缺少 GpuProcessor")
        return processor_cls

    def _make_gpu_processor(self, target_width=4, target_height=4):
        processor_cls = self._load_gpu_processor()
        try:
            return processor_cls(
                target_width,
                target_height,
                None,
                None,
                0,
                0,
                None,
                0,
                0,
                0,
                0,
                0.0,
                0.0,
            )
        except RuntimeError as exc:
            raise unittest.SkipTest(f"GpuProcessor 初始化失败: {exc}")

    def test_gpu_processor_accepts_bytes_and_ndarray_buffers(self):
        processor = self._make_gpu_processor()
        frame = np.arange(4 * 4 * 3, dtype=np.uint8).reshape((4, 4, 3))
        params = [(1.0, 2.0, 2.0, 1.0, 1.0)]
        clicks = [[]]

        result_from_bytes = processor.process_batch([frame.tobytes()], 4, 4, params, clicks)
        result_from_array = processor.process_batch([frame], 4, 4, params, clicks)
        result_from_memoryview = processor.process_batch([memoryview(frame)], 4, 4, params, clicks)

        self.assertIsInstance(result_from_bytes, bytearray)
        self.assertIsInstance(result_from_array, bytearray)
        self.assertIsInstance(result_from_memoryview, bytearray)
        self.assertEqual(bytes(result_from_bytes), bytes(result_from_array))
        self.assertEqual(bytes(result_from_array), bytes(result_from_memoryview))
        self.assertEqual(len(result_from_array), 4 * 4 * 3 // 2)

    def test_gpu_processor_rejects_non_contiguous_buffer(self):
        processor = self._make_gpu_processor()
        frame = np.arange(4 * 4 * 3, dtype=np.uint8).reshape((4, 4, 3))
        non_contiguous = frame[:, ::2, :]
        params = [(1.0, 1.0, 2.0, 1.0, 1.0)]
        clicks = [[]]

        with self.assertRaisesRegex(ValueError, "C-contiguous"):
            processor.process_batch([non_contiguous], 2, 4, params, clicks)

    def test_gpu_processor_rejects_wrong_length_buffer(self):
        processor = self._make_gpu_processor()
        params = [(1.0, 2.0, 2.0, 1.0, 1.0)]
        clicks = [[]]

        with self.assertRaisesRegex(ValueError, "length mismatch"):
            processor.process_batch([b"\x00" * 12], 4, 4, params, clicks)


if __name__ == "__main__":
    unittest.main()
