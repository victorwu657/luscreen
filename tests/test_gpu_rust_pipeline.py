import os
import sys
import unittest


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


PROJECT_ROOT = _project_root()
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.video_processor import VideoProcessor


class _FakeGpuProcessor:
    def __init__(self, max_batch_size):
        self._max_batch_size = max_batch_size

    def max_batch_size(self):
        return self._max_batch_size


class _BrokenRustStateEngine:
    def advance_batch(self, _frame_indices):
        raise RuntimeError("forced gpu-state fallback")


class TestGpuRustPipeline(unittest.TestCase):
    FLOAT_DELTA = 1e-4

    def _load_frame_state_engine(self):
        try:
            rust_core = VideoProcessor._load_rust_core(
                required_attrs=("ParallelProcessor", "GpuProcessor", "FrameStateEngine"),
                context="test_gpu_rust_pipeline",
            )
        except ImportError as exc:
            raise unittest.SkipTest(f"rust_core 不可用: {exc}")

        engine_cls = getattr(rust_core, "FrameStateEngine", None)
        if engine_cls is None:
            raise unittest.SkipTest("rust_core 缺少 FrameStateEngine")
        return engine_cls

    def _make_video_processor(self, width=1920, height=1080, fps=30.0, dpi_scale_x=1.0, dpi_scale_y=1.0):
        vp = VideoProcessor("dummy.mp4", None, "out.mp4", base_zoom=1.0, click_zoom=1.5, fps=fps, click_duration=2.0, use_gpu=True)
        vp.source_fps = fps
        vp.dpi_scale_x = dpi_scale_x
        vp.dpi_scale_y = dpi_scale_y
        segment_state = vp._reset_segment_state(width, height)
        return vp, segment_state

    def _python_states(self, mouse_data, frame_indices, width=1920, height=1080, fps=30.0, dpi_scale_x=1.0, dpi_scale_y=1.0):
        vp, segment_state = self._make_video_processor(width, height, fps, dpi_scale_x, dpi_scale_y)
        dt = 1.0 / fps if fps > 0 else 0.033
        states = []
        for frame_idx in frame_indices:
            mx, my, click, zoom, cam_x, cam_y, clicks, segment_state["click_timer"], segment_state["last_click_focus_x"], segment_state["last_click_focus_y"], segment_state["mouse_idx"] = \
                vp._update_state(
                    frame_idx,
                    mouse_data,
                    segment_state["mouse_idx"],
                    width,
                    height,
                    dt,
                    segment_state["last_click_state"],
                    segment_state["click_timer"],
                    segment_state["last_click_focus_x"],
                    segment_state["last_click_focus_y"],
                )
            segment_state["last_click_state"] = click
            states.append({
                "mouse_x": mx,
                "mouse_y": my,
                "click": click,
                "zoom": zoom,
                "cam_x": cam_x,
                "cam_y": cam_y,
                "clicks": list(clicks),
            })
        return states

    def _batch_states(self, batch_params, batch_clicks):
        states = []
        for params, clicks in zip(batch_params, batch_clicks):
            zoom, cam_x, cam_y, mouse_x, mouse_y = params
            states.append({
                "mouse_x": mouse_x,
                "mouse_y": mouse_y,
                "zoom": zoom,
                "cam_x": cam_x,
                "cam_y": cam_y,
                "clicks": list(clicks),
            })
        return states

    def _assert_batch_matches_python(self, py_states, batch_states):
        self.assertEqual(len(py_states), len(batch_states))
        for py_state, batch_state in zip(py_states, batch_states):
            self.assertAlmostEqual(py_state["mouse_x"], batch_state["mouse_x"], delta=self.FLOAT_DELTA)
            self.assertAlmostEqual(py_state["mouse_y"], batch_state["mouse_y"], delta=self.FLOAT_DELTA)
            self.assertAlmostEqual(py_state["zoom"], batch_state["zoom"], delta=self.FLOAT_DELTA)
            self.assertAlmostEqual(py_state["cam_x"], batch_state["cam_x"], delta=self.FLOAT_DELTA)
            self.assertAlmostEqual(py_state["cam_y"], batch_state["cam_y"], delta=self.FLOAT_DELTA)
            self.assertEqual(len(py_state["clicks"]), len(batch_state["clicks"]))
            for py_click, batch_click in zip(py_state["clicks"], batch_state["clicks"]):
                self.assertAlmostEqual(py_click[0], batch_click[0], delta=self.FLOAT_DELTA)
                self.assertAlmostEqual(py_click[1], batch_click[1], delta=self.FLOAT_DELTA)
                self.assertAlmostEqual(py_click[2], batch_click[2], delta=self.FLOAT_DELTA)
                self.assertAlmostEqual(py_click[3], batch_click[3], delta=self.FLOAT_DELTA)

    def test_gpu_state_batches_match_python_when_rust_engine_is_used(self):
        mouse_data = [
            {"t": 0.0, "x": 120, "y": 220, "click": False, "region_x": 10, "region_y": 20},
            {"t": 0.05, "x": 200, "y": 260, "click": True, "region_x": 10, "region_y": 20},
            {"t": 0.12, "x": 280, "y": 310, "click": False, "region_x": 10, "region_y": 20},
            {"t": 0.25, "x": 340, "y": 360, "click": True, "region_x": 10, "region_y": 20},
        ]
        frame_indices = [0, 1, 2, 3, 4, 5]
        vp, segment_state = self._make_video_processor(dpi_scale_x=1.25, dpi_scale_y=1.25)
        engine_cls = self._load_frame_state_engine()
        rust_state_engine = engine_cls(1.0, 1.5, 2.0, 30.0, 1920, 1080, 1.25, 1.25, mouse_data)
        rust_state_engine.reset_segment(1920, 1080)

        batch_params = []
        batch_clicks = []
        rust_state_engine, state_source, _state_ms = vp._fill_batch_states(
            frame_indices,
            mouse_data,
            segment_state,
            rust_state_engine,
            1920,
            1080,
            batch_params,
            batch_clicks,
        )

        self.assertIsNotNone(rust_state_engine)
        self.assertEqual(state_source, "rust")
        self._assert_batch_matches_python(
            self._python_states(mouse_data, frame_indices, dpi_scale_x=1.25, dpi_scale_y=1.25),
            self._batch_states(batch_params, batch_clicks),
        )

    def test_gpu_state_batches_fallback_to_python_when_rust_engine_fails(self):
        mouse_data = [
            {"t": 0.0, "x": 120, "y": 220, "click": False},
            {"t": 0.06, "x": 160, "y": 260, "click": True},
            {"t": 0.12, "x": 220, "y": 300, "click": False},
        ]
        frame_indices = [0, 1, 2, 3]
        vp, segment_state = self._make_video_processor()

        batch_params = []
        batch_clicks = []
        rust_state_engine, state_source, _state_ms = vp._fill_batch_states(
            frame_indices,
            mouse_data,
            segment_state,
            _BrokenRustStateEngine(),
            1920,
            1080,
            batch_params,
            batch_clicks,
        )

        self.assertIsNone(rust_state_engine)
        self.assertEqual(state_source, "python_fallback")
        self._assert_batch_matches_python(
            self._python_states(mouse_data, frame_indices),
            self._batch_states(batch_params, batch_clicks),
        )

    def test_gpu_fallback_continues_from_synced_runtime_state(self):
        mouse_data = [
            {"t": 0.0, "x": 120, "y": 220, "click": False},
            {"t": 0.03, "x": 180, "y": 260, "click": True},
            {"t": 0.10, "x": 260, "y": 320, "click": False},
            {"t": 0.20, "x": 320, "y": 360, "click": True},
        ]
        first_batch = [0, 1, 2, 3]
        second_batch = [4, 5, 6]
        vp, segment_state = self._make_video_processor()
        engine_cls = self._load_frame_state_engine()
        rust_state_engine = engine_cls(1.0, 1.5, 2.0, 30.0, 1920, 1080, 1.0, 1.0, mouse_data)
        rust_state_engine.reset_segment(1920, 1080)

        first_params = []
        first_clicks = []
        rust_state_engine, state_source, _state_ms = vp._fill_batch_states(
            first_batch,
            mouse_data,
            segment_state,
            rust_state_engine,
            1920,
            1080,
            first_params,
            first_clicks,
        )
        self.assertEqual(state_source, "rust")

        second_params = []
        second_clicks = []
        rust_state_engine, state_source, _state_ms = vp._fill_batch_states(
            second_batch,
            mouse_data,
            segment_state,
            None,
            1920,
            1080,
            second_params,
            second_clicks,
        )
        self.assertIsNone(rust_state_engine)
        self.assertEqual(state_source, "python")

        combined_states = self._batch_states(first_params, first_clicks) + self._batch_states(second_params, second_clicks)
        self._assert_batch_matches_python(
            self._python_states(mouse_data, first_batch + second_batch),
            combined_states,
        )

    def test_gpu_batch_size_respects_processor_limit(self):
        vp, _segment_state = self._make_video_processor()
        vp.gpu_processor = _FakeGpuProcessor(8)
        vp.rust_processor = None
        self.assertEqual(vp._get_effective_batch_size(), 8)

        vp.gpu_processor = _FakeGpuProcessor(24)
        self.assertEqual(vp._get_effective_batch_size(), 12)


if __name__ == "__main__":
    unittest.main()
